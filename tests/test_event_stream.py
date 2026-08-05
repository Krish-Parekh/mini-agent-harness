from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from fastapi import FastAPI

from backend.api.conversations import router as conversations_router
from backend.api.streaming import stream_conversation
from backend.runtime.manager import EventBroker
from backend.schemas import StatusUpdate
from miniagent.conversation import Status
from miniagent.events import ErrorEvent, MessageEvent
from tests.fakes import FakeConnectionRepository, FakeUserRepository


class FakeConversationState:
    def __init__(self, events) -> None:
        self.events = events
        self.status = Status.IDLE


class FakeStreamManaged:
    def __init__(self, cid: str, user_id: uuid.UUID, events, broker) -> None:
        self.id = cid
        self.user_id = user_id
        self.repo = None
        self.conversation = FakeConversationState(events)
        self.broker = broker


class FakeStreamService:
    def __init__(self) -> None:
        self.conversations: dict[str, FakeStreamManaged] = {}

    async def get_or_revive(self, cid: str, user_id: uuid.UUID):
        managed = self.conversations.get(cid)
        return managed if managed and managed.user_id == user_id else None


def message(text: str) -> MessageEvent:
    return MessageEvent(role="user", text=text)


@pytest.fixture
async def managed(user_a) -> FakeStreamManaged:
    return FakeStreamManaged(
        "c1",
        uuid.UUID(user_a.sub),
        [message("first"), message("second"), message("third")],
        EventBroker(asyncio.get_running_loop()),
    )


async def take(managed, last_event_id, count):
    frames = []
    stream = stream_conversation(managed, last_event_id)
    async for frame in stream:
        frames.append(frame)
        if len(frames) >= count:
            break
    await stream.aclose()
    return frames


async def test_replays_every_event_with_its_seq_then_status(managed):
    frames = await take(managed, None, 4)

    assert [f.event for f in frames] == ["message", "message", "message", "status"]
    assert [f.id for f in frames[:3]] == ["1", "2", "3"]
    assert StatusUpdate.model_validate_json(frames[3].raw_data).status == "idle"


async def test_status_frame_carries_no_id(managed):
    frames = await take(managed, None, 4)
    assert frames[3].event == "status"
    assert frames[3].id is None


async def test_last_event_id_resumes_without_replaying_history(managed):
    frames = await take(managed, 2, 2)

    assert frames[0].event == "message"
    assert frames[0].id == "3"
    assert frames[1].event == "status"


async def test_last_event_id_at_head_replays_no_events(managed):
    frames = await take(managed, 3, 1)
    assert frames[0].event == "status"


async def test_live_event_uses_the_seq_the_broker_published(managed):
    stream = stream_conversation(managed, 3)
    frames = [await anext(stream)]

    managed.broker.publish_event(message("fourth"), seq=4)
    frames.append(await anext(stream))
    await stream.aclose()

    assert frames[0].event == "status"
    assert frames[1].event == "message"
    assert frames[1].id == "4"


async def test_a_seqless_frame_is_sent_without_an_id(managed):
    stream = stream_conversation(managed, 3)
    await anext(stream)

    managed.broker.publish_event(ErrorEvent(message="persistence died"), seq=None)
    frame = await anext(stream)
    await stream.aclose()

    assert frame.event == "error"
    assert frame.id is None


async def test_replayed_events_are_not_resent_when_they_arrive_live(managed):
    already = managed.conversation.events[2]
    stream = stream_conversation(managed, None)
    for _ in range(4):
        await anext(stream)

    managed.broker.publish_event(already, seq=3)
    managed.broker.publish_event(message("fourth"), seq=4)
    frame = await anext(stream)
    await stream.aclose()

    assert frame.id == "4"


@pytest.fixture
async def client(verifier, user_a, user_b, managed):
    application = FastAPI()
    application.include_router(conversations_router)
    users = FakeUserRepository()
    await users.upsert(user_id=uuid.UUID(user_a.sub), email=None, avatar_url=None)
    await users.upsert(user_id=uuid.UUID(user_b.sub), email=None, avatar_url=None)
    service = FakeStreamService()
    service.conversations["c1"] = managed

    application.state.verifier = verifier
    application.state.users = users
    application.state.connections = FakeConnectionRepository()
    application.state.service = service

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client


async def test_stream_requires_authentication(client):
    response = await client.get("/conversations/c1/events/stream")
    assert response.status_code == 401


async def test_stream_rejects_a_garbage_token(client):
    response = await client.get(
        "/conversations/c1/events/stream",
        headers={"Authorization": "Bearer nonsense"},
    )
    assert response.status_code == 401


async def test_foreign_conversation_is_not_found(client):
    response = await client.get(
        "/conversations/c1/events/stream",
        headers={"Authorization": "Bearer token-b"},
    )
    assert response.status_code == 404
