from __future__ import annotations

import asyncio
from pathlib import Path

from miniagent.agent import Agent
from miniagent.config import Settings
from miniagent.confirm import ConfirmMode, ConfirmPolicy
from miniagent.conversation import Conversation
from miniagent.events import Event
from miniagent.llm import LLM
from miniagent.sandbox.local import LocalSandbox
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
    ) -> None:
        self.conversation = conversation
        self.sandbox = sandbox
        self.broker = broker
        self.events_path = events_path
        self.lock = asyncio.Lock()

    def on_event(self, event: Event) -> None:
        with self.events_path.open("a") as fh:
            fh.write(event.model_dump_json() + "\n")
        self.broker.publish(event)


class ConversationManager:
    def __init__(self, settings: Settings, events_dir: Path) -> None:
        self._settings = settings
        self._events_dir = events_dir
        self._events_dir.mkdir(parents=True, exist_ok=True)
        self._conversations: dict[str, ManagedConversation] = {}
        self._tasks: set[asyncio.Task] = set()

    def create(
        self,
        workspace_dir: str | None = None,
        confirm_mode: ConfirmMode = "risky",
    ) -> ManagedConversation:
        loop = asyncio.get_running_loop()
        sandbox = LocalSandbox(workspace_dir or self._settings.workspace_dir)
        conversation = Conversation(
            agent=_build_agent(self._settings),
            sandbox=sandbox,
            confirm_policy=ConfirmPolicy(confirm_mode),
        )
        broker = EventBroker(loop)
        events_path = self._events_dir / f"{conversation.id}.jsonl"
        managed = ManagedConversation(conversation, sandbox, broker, events_path)
        conversation.on_event = managed.on_event
        self._conversations[conversation.id] = managed
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
        task = asyncio.create_task(self._run(managed, trigger))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, managed: ManagedConversation, trigger) -> None:
        async with managed.lock:
            await asyncio.to_thread(trigger)
