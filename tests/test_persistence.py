from __future__ import annotations

import asyncio
import uuid

import pytest

from backend.runtime.manager import EventBroker, StreamFrame
from backend.schemas import StatusUpdate
from backend.service.conversation import ConversationService
from miniagent.conversation import Status
from miniagent.events import ErrorEvent, MessageEvent


class FlakyRepository:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0
        self.written: list[dict] = []

    async def record_event(self, **kwargs) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("database is down")
        self.written.append(kwargs)


class FakeSandbox:
    workspace_dir = "/tmp/workspace"


class FakeConversationState:
    def __init__(self) -> None:
        self.id = "c1"
        self.events: list = []
        self.status = Status.RUNNING
        self.plan = None
        self.implementing_plan = False


class FakeManagedConversation:
    def __init__(self, broker: EventBroker) -> None:
        self.conversation = FakeConversationState()
        self.user_id = uuid.uuid4()
        self.repo = None
        self.branch = None
        self.title = None
        self.sandbox = FakeSandbox()
        self.broker = broker


@pytest.fixture
async def broker() -> EventBroker:
    return EventBroker(asyncio.get_running_loop())


@pytest.fixture
async def managed(broker) -> FakeManagedConversation:
    return FakeManagedConversation(broker)


def service_for(repo) -> ConversationService:
    return ConversationService(manager=None, repository=repo, connections=None)


async def drain(queue: asyncio.Queue) -> list:
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


async def test_a_transient_failure_is_retried_and_then_succeeds(managed):
    repo = FlakyRepository(failures=2)
    service = service_for(repo)
    subscriber = managed.broker.subscribe()

    await service._write_event(managed, MessageEvent(role="user", text="hi"), 1)

    assert repo.calls == 3
    assert len(repo.written) == 1
    assert await drain(subscriber) == []


async def test_giving_up_raises_so_the_worker_can_report_it(managed):
    service = service_for(FlakyRepository(failures=99))

    with pytest.raises(RuntimeError):
        await service._write_event(managed, MessageEvent(role="user", text="hi"), 1)


async def test_a_final_failure_errors_the_conversation_and_tells_the_client(managed):
    service = service_for(FlakyRepository(failures=99))
    subscriber = managed.broker.subscribe()
    event = MessageEvent(role="user", text="hi")

    service._report_persist_failure(managed, event, RuntimeError("database is down"))
    await asyncio.sleep(0)

    assert managed.conversation.status == Status.ERROR

    published = await drain(subscriber)
    frames = [i for i in published if isinstance(i, StreamFrame)]
    statuses = [i for i in published if isinstance(i, StatusUpdate)]

    assert len(frames) == 1
    assert isinstance(frames[0].event, ErrorEvent)
    assert frames[0].seq is None
    assert event.id in frames[0].event.message
    assert [s.status for s in statuses] == ["error"]


async def test_the_failure_event_is_never_itself_persisted(managed):
    repo = FlakyRepository(failures=99)
    service = service_for(repo)

    service._report_persist_failure(
        managed, MessageEvent(role="user", text="hi"), RuntimeError("down")
    )
    await asyncio.sleep(0)

    assert repo.written == []
    assert managed.conversation.events == []


async def test_client_event_id_reaches_the_repository(managed):
    repo = FlakyRepository(failures=0)
    service = service_for(repo)
    event = MessageEvent(role="user", text="hi", client_event_id="abc-123")

    await service._write_event(managed, event, 1)

    assert repo.written[0]["client_event_id"] == "abc-123"


async def test_events_without_a_client_event_id_write_none(managed):
    repo = FlakyRepository(failures=0)
    service = service_for(repo)

    await service._write_event(managed, ErrorEvent(message="boom"), 1)

    assert repo.written[0]["client_event_id"] is None
