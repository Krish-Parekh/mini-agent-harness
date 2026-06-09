from __future__ import annotations

import asyncio
from functools import partial
from typing import Any, Callable

from pydantic import TypeAdapter
from sqlalchemy import func

from backend.runtime.manager import (
    AI_TITLE_AFTER_TURNS,
    ConversationManager,
    ManagedConversation,
)
from backend.repository import ConversationRepository
from backend.schemas import ConversationInfo, StatusUpdate
from miniagent.conversation import Status
from miniagent.events import Event, Events

_EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Events)


class ConversationService:
    """Use-case layer: orchestrates the runtime (manager) and persistence
    (repository), and owns the single-writer worker that drains events to the DB.
    """

    def __init__(
        self, manager: ConversationManager, repository: ConversationRepository
    ) -> None:
        self._manager = manager
        self._repo = repository
        self._persist_queue: asyncio.Queue[tuple[ManagedConversation, Event, int]] = (
            asyncio.Queue()
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._persist_task: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()

    # --- startup -----------------------------------------------------------

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._manager.set_persist_hook(self._enqueue_persist)
        self._persist_task = asyncio.create_task(self._persistence_worker())

    # --- persistence (single writer) --------------------------------------

    def _enqueue_persist(
        self, managed: ManagedConversation, event: Event, seq: int
    ) -> None:
        assert self._loop is not None
        self._loop.call_soon_threadsafe(
            self._persist_queue.put_nowait, (managed, event, seq)
        )

    async def _persistence_worker(self) -> None:
        while True:
            managed, event, seq = await self._persist_queue.get()
            try:
                await self._repo.record_event(
                    cid=managed.conversation.id,
                    repo=managed.repo,
                    branch=managed.branch,
                    status=managed.conversation.status.value,
                    title=managed.title,
                    workspace_dir=managed.sandbox.workspace_dir,
                    event_id=event.id,
                    seq=seq,
                    source=event.source,
                    kind=event.kind,
                    payload=event.model_dump(),
                )
            except Exception as exc:  # best-effort durability for v1
                print(f"[persist] failed to write event {event.id}: {exc}")
            finally:
                self._persist_queue.task_done()

    def _emit_status(self, managed: ManagedConversation, status: str | None = None) -> None:
        """Push the conversation's status to live WS subscribers (push, not poll)."""
        managed.broker.publish(
            StatusUpdate(status=status or managed.conversation.status.value)
        )

    async def _persist_status(
        self,
        managed: ManagedConversation,
        lane: str | None = None,
        run_started: bool | None = None,
    ) -> None:
        if lane is not None:
            managed.lane = lane
        # run_started: True stamps the run start, False clears it, None leaves it.
        run_kwargs: dict[str, Any] = {}
        if run_started is True:
            run_kwargs["run_started_at"] = func.now()
        elif run_started is False:
            run_kwargs["run_started_at"] = None
        await self._repo.upsert_conversation(
            cid=managed.conversation.id,
            repo=managed.repo,
            branch=managed.branch,
            status=managed.conversation.status.value,
            title=managed.title,
            workspace_dir=managed.sandbox.workspace_dir,
            lane=lane,
            **run_kwargs,
        )

    # --- use cases ---------------------------------------------------------

    def create(
        self,
        *,
        repo: str | None,
        branch: str | None,
        workspace_dir: str | None,
        confirm_mode,
        token: str | None,
        initial_message: str | None,
    ) -> ManagedConversation:
        managed = self._manager.create(
            repo=repo,
            branch=branch,
            workspace_dir=workspace_dir,
            confirm_mode=confirm_mode,
            token=token,
        )
        if repo or initial_message:
            managed.lane = "working"
            self._spawn(self._start(managed, initial_message))
        else:
            # Nothing runs yet — it sits in Todo until started.
            managed.lane = "todo"
            self._spawn(self._persist_status(managed, lane="todo"))
        return managed

    async def send_message(
        self,
        managed: ManagedConversation,
        text: str,
        model: str | None = None,
        plan_mode: bool = False,
    ) -> None:
        if model:
            managed.set_model(model)
        managed.conversation.send_message(text, plan_mode=plan_mode)
        self._spawn(self._run(managed, managed.conversation.run))

    async def confirm(
        self, managed: ManagedConversation, approve: bool, reason: str
    ) -> None:
        if approve:
            trigger: Callable[[], None] = managed.conversation.approve
        else:
            trigger = partial(managed.conversation.reject, reason)
        self._spawn(self._run(managed, trigger))

    async def set_lane(self, managed: ManagedConversation, lane: str) -> None:
        """Manual board move (e.g. In Review -> Done, or requeue to Todo)."""
        await self._persist_status(managed, lane=lane)

    async def get_or_revive(self, cid: str) -> ManagedConversation | None:
        managed = self._manager.get(cid)
        if managed is not None:
            return managed
        return await self._revive(cid)

    async def _revive(self, cid: str) -> ManagedConversation | None:
        row = await self._repo.get(cid)
        if row is None:
            return None
        event_rows = await self._repo.list_events(cid)
        events = [_EVENT_ADAPTER.validate_python(r.payload) for r in event_rows]
        return self._manager.register_revived(
            cid=cid,
            repo=row.repo,
            branch=row.branch,
            workspace_dir=row.workspace_dir,
            status=row.status,
            title=row.title,
            lane=row.lane,
            events=events,
        )

    async def list_infos(self) -> list[ConversationInfo]:
        summaries = await self._repo.list_summaries()
        return [
            ConversationInfo(
                id=row.id,
                status=row.status,
                lane=row.lane,
                workspace_dir=row.workspace_dir or "",
                num_events=count,
                repo=row.repo,
                branch=row.branch,
                title=row.title,
                created_at=row.created_at,
                run_started_at=row.run_started_at,
                updated_at=row.updated_at,
            )
            for row, count in summaries
        ]

    async def delete(self, cid: str) -> bool:
        row = await self._repo.get(cid)
        managed = self._manager.remove(cid)
        if managed is not None:
            managed.conversation.set_finished()
            await asyncio.to_thread(managed.sandbox.close)
        repo = (managed.repo if managed else None) or (row.repo if row else None)
        await asyncio.to_thread(self._manager.release_workspace, cid, repo)
        deleted = await self._repo.delete(cid)
        return deleted or managed is not None

    def info(self, managed: ManagedConversation) -> ConversationInfo:
        conv = managed.conversation
        return ConversationInfo(
            id=conv.id,
            status=conv.status.value,
            lane=managed.lane,
            workspace_dir=managed.sandbox.workspace_dir,
            num_events=len(conv.events),
            repo=managed.repo,
            branch=managed.branch,
            title=managed.title,
        )

    # --- agent runs --------------------------------------------------------

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # While a run is in flight the card sits in Working; when it ends it moves
    # to In Review for the user to look at (unless they've already marked Done).
    def _settled_lane(self, managed: ManagedConversation) -> str | None:
        return None if managed.lane == "done" else "review"

    async def _run(self, managed: ManagedConversation, trigger) -> None:
        self._emit_status(managed, "running")
        await self._persist_status(managed, lane="working", run_started=True)
        async with managed.lock:
            await asyncio.to_thread(trigger)
        await self._maybe_ai_title(managed)
        self._emit_status(managed)
        await self._persist_status(
            managed, lane=self._settled_lane(managed), run_started=False
        )

    async def _maybe_ai_title(self, managed: ManagedConversation) -> None:
        """Upgrade the heuristic title to an AI one once there are enough turns.
        Best-effort: on failure we keep the heuristic title and retry next run."""
        if managed._ai_titled or managed.user_turns() < AI_TITLE_AFTER_TURNS:
            return
        try:
            title = await asyncio.to_thread(managed.build_title)
        except Exception as exc:  # title is cosmetic — never fail the run
            print(f"[title] generation failed for {managed.conversation.id}: {exc}")
            return
        if title:
            managed.title = title
            managed._ai_titled = True

    async def _start(
        self, managed: ManagedConversation, initial_message: str | None
    ) -> None:
        self._emit_status(managed, "running")
        await self._persist_status(managed, lane="working", run_started=True)
        async with managed.lock:
            await asyncio.to_thread(managed.bootstrap)
            if managed.conversation.status == Status.ERROR:
                self._emit_status(managed)
                await self._persist_status(
                    managed, lane=self._settled_lane(managed), run_started=False
                )
                return
            if initial_message:
                managed.conversation.send_message(initial_message)
                await asyncio.to_thread(managed.conversation.run)
        self._emit_status(managed)
        await self._persist_status(
            managed, lane=self._settled_lane(managed), run_started=False
        )
