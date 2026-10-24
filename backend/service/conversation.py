from __future__ import annotations

import asyncio
import logging
import time
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
    QueuedMessage,
    publish_committed,
)
from backend.repository import (
    ConversationRepository,
    GitHubConnectionRepository,
    McpConnectionRepository,
    SkillRepository,
)
from backend.service.extension import McpService, SkillService, render_skills
from miniagent.agent import ContextWindow
from miniagent.tracing import trace_attributes
from backend.runtime import changes, checkpoints, pulls
from fastmcp.mcp_config import MCPConfig
from backend.runtime.checkpoints import CheckpointError
from backend.runtime.attachments import (
    ATTACHMENTS_DIR,
    LINK_TTL_S,
    AttachmentError,
    Storage,
    copy_into_sandbox,
)
from backend.runtime.workspaces import BRANCH_PREFIX
from backend.schemas import (
    AttachmentIn,
    ChangedFile,
    ChangeSide,
    ContextChanges,
    ContextCounts,
    ContextError,
    ContextNote,
    ContextUsage,
    ConversationContext,
    ConversationInfo,
    FileContent,
    FileDiff,
    PrProgress,
    QueuedOut,
    QueueUpdate,
    StatusUpdate,
    TurnInfo,
)
from miniagent.confirm import PermissionMode
from miniagent.conversation import Status
from miniagent.sandbox.base import SandboxError, SandboxExpired
from miniagent.events import (
    Attachment,
    CondensationEvent,
    ErrorEvent,
    Event,
    Events,
    LLMUsageEvent,
    MessageEvent,
    RepoInstructionsEvent,
    WorkerEvent,
    WorkerStatusEvent,
    WorkspaceSketchEvent,
)

_EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Events)


def _add_usage(usage: ContextUsage, event: LLMUsageEvent) -> None:
    usage.prompt_tokens += event.prompt_tokens
    usage.completion_tokens += event.completion_tokens
    usage.total_tokens += event.total_tokens
    usage.cached_prompt_tokens += event.cached_prompt_tokens
    usage.cost_usd += event.cost_usd

_PERSIST_ATTEMPTS = 3
_log = logging.getLogger(__name__)


class ConversationService:

    def __init__(
        self,
        manager: ConversationManager,
        repository: ConversationRepository,
        connections: GitHubConnectionRepository,
        skills: SkillRepository | None = None,
        mcp: McpConnectionRepository | None = None,
        storage: Storage | None = None,
        mcp_config: MCPConfig | None = None,
    ) -> None:
        self._manager = manager
        self._repo = repository
        self._connections = connections
        self._skills = skills
        self._mcp = mcp
        self._storage = storage
        self._mcp_config = mcp_config
        self._persist_queue: asyncio.Queue[tuple[ManagedConversation, Event, int]] = (
            asyncio.Queue()
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._persist_task: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        self._change_feeds: dict[uuid.UUID, set[asyncio.Queue[str]]] = {}

    def subscribe_changes(self, user_id: uuid.UUID) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._change_feeds.setdefault(user_id, set()).add(queue)
        return queue

    def unsubscribe_changes(self, user_id: uuid.UUID, queue: asyncio.Queue[str]) -> None:
        feeds = self._change_feeds.get(user_id, set())
        feeds.discard(queue)
        if not feeds:
            self._change_feeds.pop(user_id, None)

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._manager.set_persist_hook(self._enqueue_persist)
        self._manager.set_status_hook(self._on_status)
        self._persist_task = asyncio.create_task(self._persistence_worker())
        self._spawn(self._idle_sweeper())

    async def _idle_sweeper(self) -> None:
        idle_s = self._manager.sandbox_idle_stop_s
        while True:
            await asyncio.sleep(min(60, idle_s))
            await self.stop_idle_sandboxes(idle_s)

    async def stop_idle_sandboxes(self, idle_s: int) -> None:
        for managed in self._manager.live():
            if managed.lock.locked() or managed.conversation.status == Status.RUNNING:
                continue
            if await asyncio.to_thread(managed.sandbox.stop_if_idle, idle_s):
                await asyncio.to_thread(managed.close_mcp)

    async def settle_interrupted_runs(self) -> None:
        for cid, last_seq in await self._repo.with_status(Status.RUNNING.value):
            event = ErrorEvent(
                message="The server restarted while this run was in progress. "
                "Send a message to continue."
            )
            await self._repo.settle(
                cid,
                status=Status.ERROR.value,
                event_id=event.id,
                seq=last_seq + 1,
                source=event.source,
                kind=event.kind,
                payload=event.model_dump(),
            )

    async def reconcile_sandboxes(self) -> None:
        try:
            containers = await asyncio.to_thread(self._manager.sandbox_containers)
        except Exception as exc:
            _log.info("skipping docker orphan cleanup: %s", exc)
            return
        known = await self._repo.existing_ids(list(containers))
        orphans = {
            cid: container
            for cid, container in containers.items()
            if cid not in known and self._manager.get(cid) is None
        }
        if orphans:
            await asyncio.to_thread(self._manager.remove_containers, orphans)


    def _enqueue_persist(
        self, managed: ManagedConversation, event: Event, seq: int
    ) -> None:
        assert self._loop is not None
        self._loop.call_soon_threadsafe(
            self._persist_queue.put_nowait, (managed, event, seq)
        )

    @staticmethod
    def _sandbox_state(managed: ManagedConversation) -> dict[str, Any]:
        return {
            "sandbox_provider": managed.sandbox.provider,
            "sandbox_id": managed.sandbox.sandbox_id,
        }

    @staticmethod
    def _agent_state(managed: ManagedConversation) -> dict[str, Any]:
        conv = managed.conversation
        return {
            "plan": conv.plan.model_dump() if conv.plan else None,
            "implementing_plan": conv.implementing_plan,
            "plan_mode": conv.plan_mode,
            "permission_mode": conv.confirm_policy.mode,
        }

    async def _persistence_worker(self) -> None:
        while True:
            managed, event, seq = await self._persist_queue.get()
            try:
                with logfire.span(
                    "persist.event",
                    conversation_id=managed.conversation.id,
                    event_id=event.id,
                    kind=event.kind,
                    seq=seq,
                ):
                    try:
                        await self._write_event(managed, event, seq)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        self._report_persist_failure(managed, event, exc)
                    else:
                        publish_committed(managed, event, seq)
            finally:
                self._persist_queue.task_done()

    async def _write_event(
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
                    **self._agent_state(managed),
                    **self._sandbox_state(managed),
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

    def _on_status(self, managed: ManagedConversation, status: Status) -> None:
        self._emit_status(managed, status.value)

    def _emit_status(self, managed: ManagedConversation, status: str | None = None) -> None:
        managed.broker.publish(
            StatusUpdate(status=status or managed.conversation.status.value)
        )

    async def _persist_status(
        self, managed: ManagedConversation, status: str | None = None
    ) -> None:
        status = status or managed.conversation.status.value
        await self._repo.upsert_conversation(
            cid=managed.conversation.id,
            user_id=managed.user_id,
            repo=managed.repo,
            branch=managed.branch,
            status=status,
            title=managed.title,
            workspace_dir=managed.sandbox.workspace_dir,
            **self._agent_state(managed),
            **self._sandbox_state(managed),
        )
        self._emit_status(managed, status)
        for queue in self._change_feeds.get(managed.user_id, ()):
            queue.put_nowait(managed.conversation.id)

    def create(
        self,
        *,
        user_id: uuid.UUID,
        repo: str | None,
        branch: str | None,
        workspace_dir: str | None,
        permission_mode: PermissionMode,
        plan_mode: bool,
        token: str | None,
        initial_message: str | None,
        model: str | None = None,
        sandbox_provider: str | None = None,
        skill_ids: list[str] | None = None,
        attachments: list[Attachment] | None = None,
        storage_token: str | None = None,
    ) -> ManagedConversation:
        skills = list(skill_ids or [])
        with logfire.span(
            "conversation.create",
            repo=repo,
            model=model,
            sandbox_provider=sandbox_provider,
            skill_count=len(skills),
        ):
            managed = self._manager.create(
                user_id=user_id,
                repo=repo,
                branch=branch,
                workspace_dir=workspace_dir,
                permission_mode=permission_mode,
                plan_mode=plan_mode,
                token=token,
                provider=sandbox_provider,
            )
        if model:
            managed.set_model(model)
        if repo or initial_message or attachments:
            self._spawn(
                self._start(managed, initial_message, skills, attachments or [], storage_token)
            )
        else:
            self._spawn(self._persist_and_enable(managed, skills))
        return managed

    async def _persist_and_enable(
        self, managed: ManagedConversation, skill_ids: list[str]
    ) -> None:
        await self._persist_status(managed)
        await self._enable_skills(managed, skill_ids)

    async def _enable_skills(
        self, managed: ManagedConversation, skill_ids: list[str]
    ) -> None:
        if self._skills is None:
            return
        for skill_id in skill_ids:
            await self._skills.set_enabled(managed.conversation.id, skill_id, True)

    async def send_message(
        self,
        managed: ManagedConversation,
        text: str,
        model: str | None = None,
        plan_mode: bool = False,
        permission_mode: PermissionMode | None = None,
        client_event_id: str | None = None,
        attachments: list[Attachment] | None = None,
        storage_token: str | None = None,
        mode: str = "steer",
    ) -> None:
        if attachments:
            await self._copy_attachments(managed, attachments, storage_token)
        conv = managed.conversation
        running = managed.lock.locked() or conv.status == Status.RUNNING
        if running and mode == "queue":
            managed.queue.append(
                QueuedMessage(
                    id=uuid.uuid4().hex[:8],
                    text=text,
                    attachments=attachments or [],
                    model=model,
                    client_event_id=client_event_id,
                    plan_mode=plan_mode,
                    permission_mode=permission_mode,
                )
            )
            self._publish_queue(managed)
            return
        if model:
            managed.set_model(model)
        if permission_mode is not None:
            conv.confirm_policy.mode = permission_mode
        if running:
            conv.plan_mode = plan_mode
            conv.steer(text, client_event_id=client_event_id, attachments=attachments)
            return
        conv.send_message(
            text,
            plan_mode=plan_mode,
            client_event_id=client_event_id,
            attachments=attachments,
        )
        self._spawn(self._run(managed, conv.run))

    def unqueue(self, managed: ManagedConversation, queued_id: str) -> bool:
        before = len(managed.queue)
        managed.queue = [q for q in managed.queue if q.id != queued_id]
        self._publish_queue(managed)
        return len(managed.queue) < before

    def _publish_queue(self, managed: ManagedConversation) -> None:
        managed.broker.publish(QueueUpdate(items=self._queued(managed)))

    @staticmethod
    def _queued(managed: ManagedConversation) -> list[QueuedOut]:
        return [QueuedOut(id=q.id, text=q.text) for q in managed.queue]

    def _continue(self, managed: ManagedConversation) -> None:
        conv = managed.conversation
        if conv.cancel_event.is_set():
            return
        if conv.has_steering():
            self._spawn(self._run(managed, conv.run))
            return
        if not managed.queue or conv.status not in (Status.IDLE, Status.FINISHED):
            return
        queued = managed.queue.pop(0)
        self._publish_queue(managed)
        if queued.model:
            managed.set_model(queued.model)
        if queued.permission_mode is not None:
            conv.confirm_policy.mode = queued.permission_mode
        conv.send_message(
            queued.text,
            plan_mode=queued.plan_mode,
            client_event_id=queued.client_event_id,
            attachments=queued.attachments,
        )
        self._spawn(self._run(managed, conv.run))

    async def _copy_attachments(
        self,
        managed: ManagedConversation,
        attachments: list[Attachment],
        storage_token: str | None,
    ) -> None:
        try:
            await asyncio.to_thread(copy_into_sandbox, managed.sandbox, attachments)
        except (AttachmentError, SandboxError):
            if self._storage is not None and storage_token:
                try:
                    await self._storage.delete(storage_token, [a.path for a in attachments])
                except AttachmentError as exc:
                    _log.warning("could not discard uploads of %s: %s", managed.conversation.id, exc)
            raise

    async def stage_attachments(
        self, user_id: uuid.UUID, token: str, attachments: list[AttachmentIn]
    ) -> list[Attachment]:
        if not attachments:
            return []
        if self._storage is None:
            raise AttachmentError("attachments are not configured on this server")
        if any(not a.path.startswith(f"{user_id}/") for a in attachments):
            raise AttachmentError("attachment does not belong to you")
        urls = await self._storage.sign(token, [a.path for a in attachments])
        expires_at = time.time() + LINK_TTL_S
        return [
            Attachment(
                **a.model_dump(),
                workspace_path=f"{ATTACHMENTS_DIR}/{a.path.split('/')[1]}/{a.name}",
                url=urls[a.path],
                expires_at=expires_at,
            )
            for a in attachments
        ]

    async def update_modes(
        self,
        managed: ManagedConversation,
        permission_mode: PermissionMode | None,
        plan_mode: bool | None,
    ) -> None:
        conv = managed.conversation
        if permission_mode is not None:
            conv.confirm_policy.mode = permission_mode
        if plan_mode is not None:
            conv.plan_mode = plan_mode
        await self._persist_status(managed)

    async def approve_plan(self, managed: ManagedConversation) -> None:
        conv = managed.conversation
        conv.implementing_plan = True
        plan_text = (
            conv.plan.render() if conv.plan is not None else "(no plan recorded)"
        )
        conv.send_message(f"The plan is approved. Implement it now.\n\n{plan_text}")
        self._spawn(self._run(managed, conv.run))

    async def confirm(
        self, managed: ManagedConversation, tool_call_id: str, approve: bool, reason: str
    ) -> None:
        if approve:
            trigger: Callable[[], None] = partial(managed.conversation.approve, tool_call_id)
        else:
            trigger = partial(managed.conversation.reject, tool_call_id, reason)
        self._spawn(self._run(managed, trigger))

    async def stop(self, managed: ManagedConversation) -> bool:
        conv = managed.conversation
        if conv.status == Status.RUNNING:
            conv.request_cancel()
            managed.sandbox.kill_running()
            return True
        if conv.status == Status.WAITING_FOR_CONFIRMATION:
            conv.set_idle()
            await self._rollback_cancelled_turn(managed, self._last_user_id(conv.live_events()))
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
            plan_mode=row.plan_mode,
            permission_mode=row.permission_mode,
            pr_number=row.pr_number,
            pr_url=row.pr_url,
            sandbox_provider=row.sandbox_provider,
            sandbox_id=row.sandbox_id,
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
                plan_mode=row.plan_mode,
                permission_mode=row.permission_mode,
                pr_number=row.pr_number,
                pr_url=row.pr_url,
                sandbox_provider=row.sandbox_provider,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row, count in summaries
        ]

    async def delete(
        self, cid: str, user_id: uuid.UUID, token: str | None = None
    ) -> bool:
        row = await self._repo.get(cid, user_id)
        live = self._manager.get(cid)
        if row is None and (live is None or live.user_id != user_id):
            return False
        if self._storage is not None and token:
            events = (
                live.conversation.events
                if live is not None
                else [
                    _EVENT_ADAPTER.validate_python(r.payload)
                    for r in await self._repo.list_events(cid)
                ]
            )
            paths = [
                a.path
                for e in events
                if isinstance(e, MessageEvent)
                for a in e.attachments
            ]
            if paths:
                try:
                    await self._storage.delete(token, paths)
                except AttachmentError as exc:
                    _log.warning("could not delete attachments of %s: %s", cid, exc)
        managed = self._manager.remove(cid)
        if managed is not None:
            managed.conversation.set_finished()
            await asyncio.to_thread(managed.close_mcp)
            await asyncio.to_thread(managed.conversation.agent.close)
            await asyncio.to_thread(managed.sandbox.close)
        elif row is not None:
            await asyncio.to_thread(
                self._manager.destroy_sandbox,
                cid,
                row.sandbox_provider,
                row.sandbox_id,
                row.workspace_dir,
            )
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
            plan_mode=conv.plan_mode,
            permission_mode=conv.confirm_policy.mode,
            pr_number=managed.pr_number,
            pr_url=managed.pr_url,
            sandbox_provider=managed.sandbox.provider,
            queued=self._queued(managed),
        )

    async def create_pr(
        self, managed: ManagedConversation, token: str
    ) -> ConversationInfo:
        conv = managed.conversation
        head = f"{BRANCH_PREFIX}/{conv.id}"
        try:
            managed.broker.publish(PrProgress(step="drafting"))
            diff = await asyncio.to_thread(pulls.staged_diff, managed.sandbox)
            template = await asyncio.to_thread(pulls.pr_template, managed.sandbox)
            draft = await asyncio.to_thread(managed.draft_pr, diff, template)
            managed.broker.publish(PrProgress(step="pushing"))
            await asyncio.to_thread(
                pulls.commit_and_push,
                managed.sandbox,
                managed.repo,
                head,
                token,
                draft.commit_message,
            )
            if managed.pr_number is None:
                managed.broker.publish(PrProgress(step="opening"))
                pr = await pulls.create_pull_request(
                    managed.repo,
                    head,
                    managed.branch,
                    token,
                    draft.title,
                    f"{draft.body}\n\n_Opened by MiniAgent._",
                )
                managed.pr_number = pr["number"]
                managed.pr_url = pr["html_url"]
                await self._repo.set_pr(conv.id, managed.pr_number, managed.pr_url)
        except Exception:
            managed.broker.publish(PrProgress(step="failed"))
            raise
        managed.broker.publish(PrProgress(step="done"))
        return self.info(managed)

    def context(self, managed: ManagedConversation) -> ConversationContext:
        conv = managed.conversation
        events = conv.events
        usage = ContextUsage()
        sketch: ContextNote | None = None
        condensation: ContextNote | None = None
        last_error: ContextError | None = None
        repo_instructions: list[str] = []
        user_turns = 0

        for event in events:
            if isinstance(event, LLMUsageEvent):
                _add_usage(usage, event)
            elif isinstance(event, WorkerEvent) and isinstance(event.event, LLMUsageEvent):
                _add_usage(usage, event.event)
            elif isinstance(event, RepoInstructionsEvent):
                repo_instructions = event.paths
            elif isinstance(event, WorkspaceSketchEvent):
                sketch = ContextNote(text=event.content, at=event.timestamp)
            elif isinstance(event, CondensationEvent) and not event.pruned_only:
                condensation = ContextNote(text=event.summary, at=event.timestamp)
            elif isinstance(event, ErrorEvent):
                last_error = ContextError(
                    message=event.message,
                    trace_id=event.trace_id,
                    at=event.timestamp,
                )
            elif isinstance(event, MessageEvent) and event.role == "user":
                user_turns += 1

        expired = False
        try:
            files = self.list_changes(managed)
        except SandboxExpired:
            files, expired = [], True
        return ConversationContext(
            repo=managed.repo,
            branch=managed.branch,
            workspace_dir=managed.sandbox.workspace_dir,
            sandbox_provider=managed.sandbox.provider,
            sandbox_expired=expired,
            model=conv.agent.llm.model,
            status=conv.status.value,
            workspace_sketch=sketch,
            repo_instructions=repo_instructions,
            condensation=condensation,
            usage=usage,
            last_error=last_error,
            session_changes=ContextChanges(
                files=len(files),
                additions=sum(f.additions for f in files),
                deletions=sum(f.deletions for f in files),
            ),
            counts=ContextCounts(events=len(events), user_turns=user_turns),
        )

    def context_window(self, managed: ManagedConversation) -> ContextWindow:
        return managed.conversation.agent.context_window(
            managed.conversation, managed.sandbox
        )

    def list_changes(self, managed: ManagedConversation, scope: str = "all") -> list[ChangedFile]:
        if managed.repo is None:
            return []
        return changes.list_changes(managed.sandbox, self._revs(managed, scope))

    def file_diff(self, managed: ManagedConversation, path: str, scope: str = "all") -> FileDiff:
        if managed.repo is None:
            return FileDiff(path=path, patch="")
        return changes.file_diff(managed.sandbox, path, self._revs(managed, scope))

    def turns(self, managed: ManagedConversation) -> list[TurnInfo]:
        if managed.repo is None:
            return []
        recorded = checkpoints.names(managed.sandbox)
        return [
            TurnInfo(id=e.id, text=e.text)
            for e in self._user_messages(managed)
            if e.id in recorded
        ]

    def _revs(self, managed: ManagedConversation, scope: str) -> str:
        if scope == "all":
            return "HEAD"
        if scope == "branch":
            base = f"origin/{managed.branch}" if managed.branch else "origin/HEAD"
            return changes.merge_base(managed.sandbox, base)
        forks = {
            e.worker_id: e
            for e in managed.conversation.events
            if isinstance(e, WorkerStatusEvent) and e.branch
        }
        if scope in forks:
            return f"{forks[scope].base} {forks[scope].branch}"
        users = [e.id for e in self._user_messages(managed)]
        if scope not in users or not checkpoints.exists(managed.sandbox, scope):
            raise CheckpointError("no checkpoint was recorded for that turn")
        later = users[users.index(scope) + 1 :]
        end = (
            checkpoints.ref(later[0])
            if later and checkpoints.exists(managed.sandbox, later[0])
            else checkpoints.snapshot(managed.sandbox)
        )
        return f"{checkpoints.ref(scope)} {end}"

    @staticmethod
    def _user_messages(managed: ManagedConversation) -> list[MessageEvent]:
        return [
            e
            for e in managed.conversation.live_events()
            if isinstance(e, MessageEvent) and e.role == "user"
        ]

    def list_files(self, managed: ManagedConversation) -> list[str]:
        if managed.repo is None:
            return []
        return changes.list_files(managed.sandbox)

    def file_content(self, managed: ManagedConversation, path: str) -> FileContent:
        return changes.file_content(managed.sandbox, path)

    def file_bytes(self, managed: ManagedConversation, path: str) -> bytes:
        return changes.file_bytes(managed.sandbox, path)

    def change_bytes(
        self, managed: ManagedConversation, path: str, scope: str, side: ChangeSide
    ) -> bytes:
        base, *head = self._revs(managed, scope).split()
        rev = base if side == "before" else (head[0] if head else None)
        return changes.file_bytes(managed.sandbox, path, rev)

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, managed: ManagedConversation, trigger) -> None:
        managed.run_generation += 1
        generation = managed.run_generation
        turn_start = self._last_user_id(managed.conversation.live_events())
        await self._persist_status(managed, Status.RUNNING.value)
        async with managed.lock:
            await asyncio.to_thread(
                managed.extend_sandbox, self._manager.sandbox_lifetime_s
            )
            await self._load_extensions(managed)
            await self._checkpoint(managed, turn_start)
            with self._turn_span(managed):
                await asyncio.to_thread(trigger)
            conv = managed.conversation
            if conv.cancel_event.is_set() and conv.status != Status.FINISHED:
                await self._rollback_cancelled_turn(managed, turn_start)
        await self._maybe_ai_title(managed)
        if managed.run_generation != generation:
            return
        await self._persist_status(managed)
        self._continue(managed)

    async def _checkpoint(self, managed: ManagedConversation, message_id: str | None) -> None:
        if managed.repo is None or message_id is None:
            return
        try:
            await asyncio.to_thread(checkpoints.record, managed.sandbox, message_id)
        except (CheckpointError, SandboxError) as exc:
            _log.warning("checkpoint failed for %s: %s", managed.conversation.id, exc)

    async def rewind(self, managed: ManagedConversation, message_id: str) -> MessageEvent:
        conv = managed.conversation
        if managed.lock.locked() or conv.status in (Status.RUNNING, Status.WAITING_FOR_CONFIRMATION):
            raise CheckpointError("stop the current run before rewinding")
        users = self._user_messages(managed)
        target = next((e for e in users if e.id == message_id), None)
        if target is None:
            raise CheckpointError("that message is not in this conversation")
        async with managed.lock:
            if managed.repo is not None:
                if not await asyncio.to_thread(checkpoints.exists, managed.sandbox, target.id):
                    raise CheckpointError("no checkpoint was recorded for that message")
                await asyncio.to_thread(checkpoints.restore, managed.sandbox, target.id)
                await asyncio.to_thread(
                    checkpoints.drop, managed.sandbox, [e.id for e in users[users.index(target):]]
                )
            conv.rewind(target.id)
        await self._persist_status(managed)
        return target

    async def _rollback_cancelled_turn(
        self, managed: ManagedConversation, turn_start: str | None
    ) -> None:
        conv = managed.conversation
        events = conv.events
        idx = next((i for i, e in enumerate(events) if e.id == turn_start), None)
        if idx is None:
            return
        removed = events[idx:]
        conv.events = events[:idx]
        managed._seq = len(conv.events)
        await self._persist_queue.join()
        await self._repo.delete_events(conv.id, [e.id for e in removed])
        managed.persisted_seq = len(conv.events)
        for event in removed[1:]:
            if isinstance(event, MessageEvent) and event.role == "user":
                conv.add_event(event)

    @staticmethod
    def _last_user_id(events: list[Event]) -> str | None:
        return next(
            (
                e.id
                for e in reversed(events)
                if isinstance(e, MessageEvent) and e.role == "user"
            ),
            None,
        )

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

    @staticmethod
    def _turn_span(managed: ManagedConversation):
        cid = managed.conversation.id
        last_user = next(
            (
                e.text
                for e in reversed(managed.conversation.events)
                if isinstance(e, MessageEvent) and e.role == "user"
            ),
            None,
        )
        span = logfire.span(
            "agent.turn",
            conversation_id=cid,
            sandbox_provider=managed.sandbox.provider,
            sandbox_id=managed.sandbox.sandbox_id,
        )
        span.set_attributes(
            trace_attributes(
                session_id=cid,
                user_id=str(managed.user_id) if managed.user_id else None,
                name=managed.title or "conversation turn",
                input=last_user,
            )
        )
        return span

    async def _load_extensions(self, managed: ManagedConversation) -> None:
        if self._skills is None or self._mcp is None:
            return
        cid = managed.conversation.id
        included, skipped = await SkillService(self._skills).enabled_catalog(
            cid, managed.user_id, managed.repo
        )
        skipped_ids = {skill.id for skill in skipped}
        for skill in skipped:
            if skill.id in managed.skills_skipped:
                continue
            managed.conversation.add_event(
                ErrorEvent(
                    message=(
                        f"Skill '{skill.name}' was skipped: the skill list for "
                        "this conversation is over its size budget."
                    )
                )
            )
        managed.skills_skipped = skipped_ids
        targets = await McpService(self._mcp, self._mcp_config).targets(
            cid, managed.host_workspace
        )
        await asyncio.to_thread(
            managed.apply_extensions,
            render_skills(included),
            {skill.name: skill.body for skill in included},
            targets,
        )

    async def _start(
        self,
        managed: ManagedConversation,
        initial_message: str | None,
        skill_ids: list[str] | None = None,
        attachments: list[Attachment] | None = None,
        storage_token: str | None = None,
    ) -> None:
        await self._persist_status(managed, Status.RUNNING.value)
        await self._enable_skills(managed, skill_ids or [])
        async with managed.lock:
            await asyncio.to_thread(managed.bootstrap)
            await self._load_extensions(managed)
            if attachments and managed.conversation.status != Status.ERROR:
                try:
                    await self._copy_attachments(managed, attachments, storage_token)
                except (AttachmentError, SandboxError) as exc:
                    managed.conversation.add_event(ErrorEvent(message=str(exc)))
                    managed.conversation.status = Status.ERROR
            if managed.conversation.status == Status.ERROR:
                await self._persist_status(managed)
                return
            if initial_message or attachments:
                managed.conversation.send_message(
                    initial_message or "",
                    plan_mode=managed.conversation.plan_mode,
                    attachments=attachments,
                )
                await self._checkpoint(
                    managed, self._last_user_id(managed.conversation.live_events())
                )
                with self._turn_span(managed):
                    await asyncio.to_thread(managed.conversation.run)
        await self._persist_status(managed)
        self._continue(managed)
