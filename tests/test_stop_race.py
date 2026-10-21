from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

from miniagent.conversation import Status
from miniagent.events import MessageEvent
from tests.test_persistence import FakeManagedConversation, broker  # noqa: F401


class Repository:
    def __init__(self) -> None:
        self.statuses: list[str] = []
        self.deleted: list[str] = []

    async def upsert_conversation(self, **kwargs) -> None:
        self.statuses.append(kwargs["status"])

    async def delete_events(self, cid: str, event_ids: list[str]) -> None:
        self.deleted.extend(event_ids)


class Managed(FakeManagedConversation):
    def __init__(self, broker) -> None:  # noqa: F811
        super().__init__(broker)
        self.conversation.cancel_event = threading.Event()
        self.conversation.add_event = lambda event: self.conversation.events.append(event)
        self.lock = asyncio.Lock()
        self._ai_titled = True
        self._seq = 0
        self.run_generation = 0
        self.queue: list = []

    def extend_sandbox(self, seconds: int) -> None:
        pass


async def test_a_stopped_run_does_not_clobber_the_next_turn(broker):  # noqa: F811
    from backend.service.conversation import ConversationService

    repo = Repository()
    service = ConversationService(
        manager=SimpleNamespace(sandbox_lifetime_s=0), repository=repo, connections=None
    )
    managed = Managed(broker)
    conv = managed.conversation
    first = MessageEvent(role="user", text="first")
    conv.events = [first]
    release = threading.Event()
    seen: list[str] = []

    def stopped_turn() -> None:
        release.wait(5)
        conv.events.append(MessageEvent(role="assistant", text="partial"))
        conv.status = Status.IDLE

    def next_turn() -> None:
        conv.cancel_event.clear()
        seen.extend(e.text for e in conv.events if isinstance(e, MessageEvent))
        conv.status = Status.IDLE

    old = asyncio.create_task(service._run(managed, stopped_turn))
    await asyncio.sleep(0.05)
    conv.cancel_event.set()
    conv.events.append(MessageEvent(role="user", text="second"))
    new = asyncio.create_task(service._run(managed, next_turn))
    await asyncio.sleep(0.05)
    release.set()
    await asyncio.gather(old, new)

    assert seen == ["second"]
    assert [e.text for e in conv.events] == ["second"]
    assert repo.statuses == ["running", "running", "idle"]
