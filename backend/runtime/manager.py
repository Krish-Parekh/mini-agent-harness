from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Callable

from miniagent.agent import Agent
from miniagent.config import Settings
from miniagent.confirm import ConfirmMode, ConfirmPolicy
from miniagent.conversation import Conversation, Status
from miniagent.events import ErrorEvent, Event, MessageEvent
from miniagent.llm import LLM
from miniagent.sandbox.local import LocalSandbox
from miniagent.sandbox.workspace import WorkspaceError
from backend.runtime.workspaces import WorkspaceManager
from miniagent.tools.bash import BashTool
from miniagent.tools.base import ToolRegistry
from miniagent.tools.file_edit import FileEditTool
from miniagent.tools.finish import FinishTool

PersistHook = Callable[["ManagedConversation", Event, int], None]


def _build_agent(settings: Settings) -> Agent:
    llm = LLM(
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
    )
    tools = ToolRegistry([BashTool(), FileEditTool(), FinishTool()])
    return Agent(llm=llm, tools=tools)


class EventBroker:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._subscribers: set[asyncio.Queue[Event]] = set()

    def subscribe(self) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: Event) -> None:
        for queue in list(self._subscribers):
            self._loop.call_soon_threadsafe(queue.put_nowait, event)


class ManagedConversation:
    """A live conversation: the agent loop's Conversation + sandbox + broker.

    `on_event` fans each event out to live subscribers and to the persistence
    hook the service installs; it carries no knowledge of how persistence works.
    """

    def __init__(
        self,
        conversation: Conversation,
        sandbox: LocalSandbox,
        broker: EventBroker,
        workspaces: WorkspaceManager,
        repo: str | None = None,
        branch: str | None = None,
        token: str | None = None,
    ) -> None:
        self.conversation = conversation
        self.sandbox = sandbox
        self.broker = broker
        self._workspaces = workspaces
        self.repo = repo
        self.branch = branch
        self._token = token
        self.title: str | None = None
        self.lane: str = "todo"
        self._seq = 0
        self.lock = asyncio.Lock()
        self.persist_hook: PersistHook = lambda *_: None

    def on_event(self, event: Event) -> None:
        self._seq += 1
        self._maybe_set_title(event)
        self.persist_hook(self, event, self._seq)
        self.broker.publish(event)

    def set_model(self, model: str) -> None:
        """Switch the model for subsequent agent steps (LLM reads it per call)."""
        self.conversation.agent.llm.model = model

    def _maybe_set_title(self, event: Event) -> None:
        if self.title is not None:
            return
        if not (isinstance(event, MessageEvent) and event.role == "user"):
            return
        text = event.text.strip()
        snippet = text.splitlines()[0][:60] if text else ""
        base = self.repo.split("/")[-1] if self.repo else None
        title = f"{base}: {snippet}".strip(": ") if base else snippet
        self.title = title or None

    def bootstrap(self) -> None:
        """Set up this conversation's isolated worktree (cloning the repo once
        if needed) before the agent runs. Runs in a worker thread."""
        if not self.repo:
            return
        try:
            worktree = self._workspaces.prepare(
                self.conversation.id, self.repo, self.branch, self._token
            )
        except WorkspaceError as exc:
            self.conversation.add_event(
                ErrorEvent(message=f"workspace setup failed: {exc}")
            )
            self.conversation.status = Status.ERROR
            return
        self.sandbox.set_working_dir(worktree)
        label = self.repo + (f" (branch {self.branch})" if self.branch else "")
        self.conversation.add_event(
            MessageEvent(
                role="system",
                text=f"Workspace ready: {label} checked out into an isolated worktree.",
            )
        )


class ConversationManager:
    """In-memory registry and factory of live conversations. No persistence."""

    def __init__(
        self, settings: Settings, data_dir: Path = Path("data")
    ) -> None:
        self._settings = settings
        self._workspaces = WorkspaceManager(data_dir)
        self._conversations: dict[str, ManagedConversation] = {}
        self._persist_hook: PersistHook = lambda *_: None

    def set_persist_hook(self, hook: PersistHook) -> None:
        self._persist_hook = hook

    def create(
        self,
        repo: str | None = None,
        branch: str | None = None,
        workspace_dir: str | None = None,
        confirm_mode: ConfirmMode = "risky",
        token: str | None = None,
    ) -> ManagedConversation:
        cid = uuid.uuid4().hex[:8]
        if repo:
            ws = str(self._workspaces.worktree_dir(cid))
        else:
            ws = workspace_dir or self._settings.workspace_dir
        managed = self._build(cid, ws, confirm_mode, repo, branch, token)
        return managed

    def release_workspace(self, cid: str, repo: str | None) -> None:
        self._workspaces.release(cid, repo)

    def register_revived(
        self,
        *,
        cid: str,
        repo: str | None,
        branch: str | None,
        workspace_dir: str | None,
        status: str,
        title: str | None,
        lane: str,
        events: list[Event],
    ) -> ManagedConversation:
        ws = workspace_dir or self._settings.workspace_dir
        managed = self._build(cid, ws, "risky", repo, branch, None)
        managed.conversation.events = events
        managed.title = title
        managed.lane = lane
        managed._seq = len(events)
        try:
            managed.conversation.status = Status(status)
        except ValueError:
            managed.conversation.status = Status.IDLE
        return managed

    def _build(
        self,
        cid: str,
        workspace_dir: str,
        confirm_mode: ConfirmMode,
        repo: str | None,
        branch: str | None,
        token: str | None,
    ) -> ManagedConversation:
        loop = asyncio.get_running_loop()
        sandbox = LocalSandbox(workspace_dir)
        conversation = Conversation(
            agent=_build_agent(self._settings),
            sandbox=sandbox,
            confirm_policy=ConfirmPolicy(confirm_mode),
            id=cid,
        )
        managed = ManagedConversation(
            conversation, sandbox, EventBroker(loop), self._workspaces, repo, branch, token
        )
        managed.persist_hook = self._persist_hook
        conversation.on_event = managed.on_event
        self._conversations[cid] = managed
        return managed

    def get(self, cid: str) -> ManagedConversation | None:
        return self._conversations.get(cid)

    def remove(self, cid: str) -> ManagedConversation | None:
        return self._conversations.pop(cid, None)
