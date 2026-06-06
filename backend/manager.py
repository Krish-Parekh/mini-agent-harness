from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from miniagent.agent import Agent
from miniagent.config import Settings
from miniagent.confirm import ConfirmMode, ConfirmPolicy
from miniagent.conversation import Conversation, Status
from miniagent.events import ErrorEvent, Event, MessageEvent
from miniagent.llm import LLM
from miniagent.sandbox.local import LocalSandbox
from miniagent.sandbox.workspace import WorkspaceError, clone_repo
from miniagent.tools.bash import BashTool
from miniagent.tools.base import ToolRegistry
from miniagent.tools.file_edit import FileEditTool
from miniagent.tools.finish import FinishTool


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
    def __init__(
        self,
        conversation: Conversation,
        sandbox: LocalSandbox,
        broker: EventBroker,
        events_path: Path,
        repo: str | None = None,
        branch: str | None = None,
        token: str | None = None,
    ) -> None:
        self.conversation = conversation
        self.sandbox = sandbox
        self.broker = broker
        self.events_path = events_path
        self.repo = repo
        self.branch = branch
        self._token = token
        self.lock = asyncio.Lock()

    def on_event(self, event: Event) -> None:
        with self.events_path.open("a") as fh:
            fh.write(event.model_dump_json() + "\n")
        self.broker.publish(event)

    def bootstrap(self) -> None:
        """Clone the repo (if any) before the agent runs. Runs in a worker thread."""
        if not self.repo:
            return
        try:
            clone_repo(self.sandbox, self.repo, self.branch, self._token)
        except WorkspaceError as exc:
            self.conversation.add_event(ErrorEvent(message=f"clone failed: {exc}"))
            self.conversation.status = Status.ERROR
            return
        label = self.repo + (f" (branch {self.branch})" if self.branch else "")
        self.conversation.add_event(
            MessageEvent(
                role="system",
                text=f"Workspace ready: cloned {label} into {self.sandbox.workspace_dir}.",
            )
        )


class ConversationManager:
    def __init__(self, settings: Settings, events_dir: Path) -> None:
        self._settings = settings
        self._events_dir = events_dir
        self._events_dir.mkdir(parents=True, exist_ok=True)
        self._workspaces_dir = events_dir.parent / "workspaces"
        self._conversations: dict[str, ManagedConversation] = {}
        self._tasks: set[asyncio.Task] = set()

    def create(
        self,
        repo: str | None = None,
        branch: str | None = None,
        workspace_dir: str | None = None,
        confirm_mode: ConfirmMode = "risky",
        token: str | None = None,
    ) -> ManagedConversation:
        loop = asyncio.get_running_loop()
        cid = uuid.uuid4().hex[:8]
        if repo:
            repo_name = repo.split("/")[-1]
            ws = str(self._workspaces_dir / cid / repo_name)
        else:
            ws = workspace_dir or self._settings.workspace_dir
        sandbox = LocalSandbox(ws)
        conversation = Conversation(
            agent=_build_agent(self._settings),
            sandbox=sandbox,
            confirm_policy=ConfirmPolicy(confirm_mode),
            id=cid,
        )
        broker = EventBroker(loop)
        events_path = self._events_dir / f"{cid}.jsonl"
        managed = ManagedConversation(
            conversation, sandbox, broker, events_path, repo, branch, token
        )
        conversation.on_event = managed.on_event
        self._conversations[cid] = managed
        return managed

    def get(self, cid: str) -> ManagedConversation | None:
        return self._conversations.get(cid)

    def list(self) -> list[ManagedConversation]:
        return list(self._conversations.values())

    async def delete(self, cid: str) -> bool:
        managed = self._conversations.pop(cid, None)
        if managed is None:
            return False
        managed.conversation.set_finished()
        await asyncio.to_thread(managed.sandbox.close)
        return True

    def run_in_background(self, managed: ManagedConversation, trigger) -> None:
        self._spawn(self._run(managed, trigger))

    def start(self, managed: ManagedConversation, initial_message: str | None) -> None:
        """Clone the workspace (if any), then run the agent on the first message."""
        self._spawn(self._start(managed, initial_message))

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, managed: ManagedConversation, trigger) -> None:
        async with managed.lock:
            await asyncio.to_thread(trigger)

    async def _start(
        self, managed: ManagedConversation, initial_message: str | None
    ) -> None:
        async with managed.lock:
            await asyncio.to_thread(managed.bootstrap)
            if managed.conversation.status == Status.ERROR:
                return
            if initial_message:
                managed.conversation.send_message(initial_message)
                await asyncio.to_thread(managed.conversation.run)
