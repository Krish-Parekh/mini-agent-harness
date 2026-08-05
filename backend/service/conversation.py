from __future__ import annotations

import asyncio
import logging
import uuid
from functools import partial
from typing import Any, Callable

import logfire
from pydantic import TypeAdapter
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential_jitter

from backend.runtime.manager import (
    AI_TITLE_AFTER_TURNS,
    ConversationManager,
    ManagedConversation,
)
from backend.repository import ConversationRepository, GitHubConnectionRepository
from backend.runtime import changes, pulls
from backend.runtime.workspaces import BRANCH_PREFIX
from backend.schemas import (
    ChangedFile,
    ConversationInfo,
    FileContent,
    FileDiff,
    StatusUpdate,
)
from miniagent.conversation import Status
from miniagent.events import ErrorEvent, Event, Events, MessageEvent

_EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Events)
_PERSIST_ATTEMPTS = 3
_log = logging.getLogger(__name__)


class ConversationService:

    def __init__(
        self,
        manager: ConversationManager,
        repository: ConversationRepository,
        connections: GitHubConnectionRepository,
    ) -> None:
        self._manager = manager
        self._repo = repository
        self._connections = connections
        self._persist_queue: asyncio.Queue[tuple[ManagedConversation, Event, int]] = (
            asyncio.Queue()
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._persist_task: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()


    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._manager.set_persist_hook(self._enqueue_persist)
        self._persist_task = asyncio.create_task(self._persistence_worker())


    def _enqueue_persist(
        self, managed: ManagedConversation, event: Event, seq: int
    ) -> None:
        assert self._loop is not None
        self._loop.call_soon_threadsafe(
            self._persist_queue.put_nowait, (managed, event, seq)
        )

    @staticmethod
    def _plan_state(managed: ManagedConversation) -> dict[str, Any]:
        conv = managed.conversation
        return {
            "plan": conv.plan.model_dump() if conv.plan else None,
            "implementing_plan": conv.implementing_plan,
        }

    async def _persistence_worker(self) -> None:
        while True:
            managed, event, seq = await self._persist_queue.get()
            try:
                await self._write_event(managed, event, seq)
            except asyncio.CancelledError:
                self._persist_queue.task_done()
                raise
            except Exception as exc:
                self._report_persist_failure(managed, event, exc)
                self._persist_queue.task_done()
            else:
                self._persist_queue.task_done()

    async def _write_event(
        self, managed: ManagedConversation, event: Event, seq: int
    ) -> None:
        with logfire.span(
            "persist.event",
            conversation_id=managed.conversation.id,
            event_id=event.id,
            kind=event.kind,
            seq=seq,
        ):
            await self._write_event_with_retry(managed, event, seq)

    async def _write_event_with_retry(
        self, managed: ManagedConversation, event: Event, seq: int
    ) -> None:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(_PERSIST_ATTEMPTS),
            wait=wait_exponential_jitter(initial=0.1, max=2.0),
            reraise=True,
        ):
            with attempt:
                await self._repo.record_event(
                    cid=managed.conversation.id,
                    user_id=managed.user_id,
                    repo=managed.repo,
                    branch=managed.branch,
                    status=managed.conversation.status.value,
                    title=managed.title,
                    workspace_dir=managed.sandbox.workspace_dir,
                    **self._plan_state(managed),
                    event_id=event.id,
                    seq=seq,
                    source=event.source,
                    kind=event.kind,
                    payload=event.model_dump(),
                    client_event_id=getattr(event, "client_event_id", None),
                )

    def _report_persist_failure(
        self, managed: ManagedConversation, event: Event, exc: Exception
    ) -> None:
        _log.error(
            "event persistence failed after %s attempts: conversation=%s event=%s: %s",
            _PERSIST_ATTEMPTS,
            managed.conversation.id,
            event.id,
            exc,
        )
        managed.conversation.status = Status.ERROR
        managed.broker.publish_event(
            ErrorEvent(
                message=(
                    f"Failed to save event {event.id} after {_PERSIST_ATTEMPTS}"
                    " attempts. This conversation is out of sync with the database"
                    " and has been stopped."
                )
            ),
            seq=None,
        )
        self._emit_status(managed, Status.ERROR.value)

    def _emit_status(self, managed: ManagedConversation, status: str | None = None) -> None:
        managed.broker.publish(
            StatusUpdate(status=status or managed.conversation.status.value)
        )

    async def _persist_status(self, managed: ManagedConversation) -> None:
        await self._repo.upsert_conversation(
            cid=managed.conversation.id,
            user_id=managed.user_id,
            repo=managed.repo,
            branch=managed.branch,
            status=managed.conversation.status.value,
            title=managed.title,
            workspace_dir=managed.sandbox.workspace_dir,
            **self._plan_state(managed),
        )


    def create(
        self,
        *,
        user_id: uuid.UUID,
        repo: str | None,
        branch: str | None,
        workspace_dir: str | None,
        confirm_mode,
        token: str | None,
        initial_message: str | None,
    ) -> ManagedConversation:
        managed = self._manager.create(
            user_id=user_id,
            repo=repo,
            branch=branch,
            workspace_dir=workspace_dir,
            confirm_mode=confirm_mode,
            token=token,
        )
        if repo or initial_message:
            self._spawn(self._start(managed, initial_message))
        else:
            self._spawn(self._persist_status(managed))
        return managed

    async def send_message(
        self,
        managed: ManagedConversation,
        text: str,
        model: str | None = None,
        plan_mode: bool = False,
        client_event_id: str | None = None,
    ) -> None:
        if model:
            managed.set_model(model)
        managed.conversation.send_message(
            text, plan_mode=plan_mode, client_event_id=client_event_id
        )
        self._spawn(self._run(managed, managed.conversation.run))

    async def approve_plan(self, managed: ManagedConversation) -> None:
        conv = managed.conversation
        conv.plan_mode = False
        conv.implementing_plan = True
        plan_text = (
            conv.plan.render() if conv.plan is not None else "(no plan recorded)"
        )
        conv.send_message(f"The plan is approved. Implement it now.\n\n{plan_text}")
        self._spawn(self._run(managed, conv.run))

    async def confirm(
        self, managed: ManagedConversation, approve: bool, reason: str
    ) -> None:
        if approve:
            trigger: Callable[[], None] = managed.conversation.approve
        else:
            trigger = partial(managed.conversation.reject, reason)
        self._spawn(self._run(managed, trigger))

    async def stop(self, managed: ManagedConversation) -> bool:
        conv = managed.conversation
        if conv.status == Status.RUNNING:
            conv.request_cancel()
            managed.sandbox.kill_running()
            return True
        if conv.status == Status.WAITING_FOR_CONFIRMATION:
            conv.set_idle()
            await self._rollback_cancelled_turn(managed)
            self._emit_status(managed)
            await self._persist_status(managed)
            return True
        return False

    async def get_or_revive(
        self, cid: str, user_id: uuid.UUID
    ) -> ManagedConversation | None:
        managed = self._manager.get(cid)
        if managed is not None:
            return managed if managed.user_id == user_id else None
        return await self._revive(cid, user_id)

    async def _revive(
        self, cid: str, user_id: uuid.UUID
    ) -> ManagedConversation | None:
        row = await self._repo.get(cid, user_id)
        if row is None:
            return None
        event_rows = await self._repo.list_events(cid)
        events = [_EVENT_ADAPTER.validate_python(r.payload) for r in event_rows]
        return self._manager.register_revived(
            cid=cid,
            user_id=row.user_id,
            token=await self._connections.token_for(row.user_id),
            repo=row.repo,
            branch=row.branch,
            workspace_dir=row.workspace_dir,
            status=row.status,
            title=row.title,
            events=events,
            plan=row.plan,
            implementing_plan=row.implementing_plan,
            pr_number=row.pr_number,
            pr_url=row.pr_url,
        )

    async def list_infos(self, user_id: uuid.UUID) -> list[ConversationInfo]:
        summaries = await self._repo.list_summaries(user_id)
        return [
            ConversationInfo(
                id=row.id,
                status=row.status,
                workspace_dir=row.workspace_dir or "",
                num_events=count,
                repo=row.repo,
                branch=row.branch,
                title=row.title,
                plan=row.plan,
                implementing_plan=row.implementing_plan,
                pr_number=row.pr_number,
                pr_url=row.pr_url,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row, count in summaries
        ]

    async def delete(self, cid: str, user_id: uuid.UUID) -> bool:
        row = await self._repo.get(cid, user_id)
        live = self._manager.get(cid)
        if row is None and (live is None or live.user_id != user_id):
            return False
        managed = self._manager.remove(cid)
        if managed is not None:
            managed.conversation.set_finished()
            await asyncio.to_thread(managed.sandbox.close)
        repo = (managed.repo if managed else None) or (row.repo if row else None)
        await asyncio.to_thread(self._manager.release_workspace, cid, repo)
        deleted = await self._repo.delete(cid, user_id)
        return deleted or managed is not None

    def info(self, managed: ManagedConversation) -> ConversationInfo:
        conv = managed.conversation
        return ConversationInfo(
            id=conv.id,
            status=conv.status.value,
            workspace_dir=managed.sandbox.workspace_dir,
            num_events=len(conv.events),
            repo=managed.repo,
            branch=managed.branch,
            title=managed.title,
            plan=conv.plan,
            implementing_plan=conv.implementing_plan,
            pr_number=managed.pr_number,
            pr_url=managed.pr_url,
        )

    async def create_pr(
        self, managed: ManagedConversation, token: str
    ) -> ConversationInfo:
        conv = managed.conversation
        head = f"{BRANCH_PREFIX}/{conv.id}"
        title = managed.title or f"MiniAgent changes for {managed.repo}"
        await asyncio.to_thread(
            pulls.commit_and_push, managed.sandbox, managed.repo, head, token, title
        )
        if managed.pr_number is None:
            pr = await pulls.create_pull_request(
                managed.repo, head, managed.branch, token, title, self._pr_body(managed)
            )
            managed.pr_number = pr["number"]
            managed.pr_url = pr["html_url"]
            await self._repo.set_pr(conv.id, managed.pr_number, managed.pr_url)
        return self.info(managed)

    @staticmethod
    def _pr_body(managed: ManagedConversation) -> str:
        lines = ["Opened by MiniAgent."]
        if managed.title:
            lines.append(f"\n{managed.title}")
        return "\n".join(lines)

    def list_changes(self, managed: ManagedConversation) -> list[ChangedFile]:
        if managed.repo is None:
            return []
        return changes.list_changes(managed.sandbox)

    def file_diff(self, managed: ManagedConversation, path: str) -> FileDiff:
        if managed.repo is None:
            return FileDiff(path=path, patch="")
        return changes.file_diff(managed.sandbox, path)

    def list_files(self, managed: ManagedConversation) -> list[str]:
        if managed.repo is None:
            return []
        return changes.list_files(managed.sandbox)

    def file_content(self, managed: ManagedConversation, path: str) -> FileContent:
        return changes.file_content(managed.sandbox, path)


    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, managed: ManagedConversation, trigger) -> None:
        self._emit_status(managed, "running")
        await self._persist_status(managed)
        async with managed.lock:
            await asyncio.to_thread(trigger)
            conv = managed.conversation
            if conv.cancel_event.is_set() and conv.status != Status.FINISHED:
                await self._rollback_cancelled_turn(managed)
        await self._maybe_ai_title(managed)
        self._emit_status(managed)
        await self._persist_status(managed)

    async def _rollback_cancelled_turn(self, managed: ManagedConversation) -> None:
        conv = managed.conversation
        events = conv.events
        idx = self._last_user_index(events)
        if idx is None:
            return
        removed = events[idx:]
        conv.events = events[:idx]
        managed._seq = len(conv.events)
        await self._persist_queue.join()
        await self._repo.delete_events(conv.id, [e.id for e in removed])

    @staticmethod
    def _last_user_index(events: list[Event]) -> int | None:
        for i in range(len(events) - 1, -1, -1):
            e = events[i]
            if isinstance(e, MessageEvent) and e.role == "user":
                return i
        return None

    async def _maybe_ai_title(self, managed: ManagedConversation) -> None:
        if managed._ai_titled or managed.user_turns() < AI_TITLE_AFTER_TURNS:
            return
        try:
            title = await asyncio.to_thread(managed.build_title)
        except Exception as exc:
            print(f"[title] generation failed for {managed.conversation.id}: {exc}")
            return
        if title:
            managed.title = title
            managed._ai_titled = True

    async def _start(
        self, managed: ManagedConversation, initial_message: str | None
    ) -> None:
        self._emit_status(managed, "running")
        await self._persist_status(managed)
        async with managed.lock:
            await asyncio.to_thread(managed.bootstrap)
            if managed.conversation.status == Status.ERROR:
                self._emit_status(managed)
                await self._persist_status(managed)
                return
            if initial_message:
                managed.conversation.send_message(initial_message)
                await asyncio.to_thread(managed.conversation.run)
        self._emit_status(managed)
        await self._persist_status(managed)
