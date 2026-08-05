from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI

from backend.api.conversations import router as conversations_router
from backend.schemas import ConversationContext
from backend.service.conversation import ConversationService
from miniagent.conversation import Status
from miniagent.events import (
    CondensationEvent,
    ErrorEvent,
    LLMUsageEvent,
    MessageEvent,
    WorkspaceSketchEvent,
)
from tests.fakes import FakeConnectionRepository, FakeUserRepository


class FakeLLM:
    model = "gpt-4o-mini"


class FakeAgent:
    llm = FakeLLM()


class FakeSandbox:
    workspace_dir = "/tmp/worktrees/c1"


class FakeConversationState:
    def __init__(self, events) -> None:
        self.id = "c1"
        self.events = events
        self.status = Status.IDLE
        self.agent = FakeAgent()


class FakeManaged:
    def __init__(self, events, repo=None) -> None:
        self.conversation = FakeConversationState(events)
        self.user_id = uuid.uuid4()
        self.repo = repo
        self.branch = "main" if repo else None
        self.title = None
        self.sandbox = FakeSandbox()


def service() -> ConversationService:
    return ConversationService(manager=None, repository=None, connections=None)


def usage(**kw) -> LLMUsageEvent:
    return LLMUsageEvent(phase="step", model="gpt-4o-mini", **kw)


def test_usage_is_summed_across_every_llm_usage_event():
    managed = FakeManaged(
        [
            usage(prompt_tokens=10, completion_tokens=2, total_tokens=12, cost_usd=0.01),
            usage(prompt_tokens=5, completion_tokens=3, total_tokens=8, cost_usd=0.02),
        ]
    )

    ctx = service().context(managed)

    assert ctx.usage.prompt_tokens == 15
    assert ctx.usage.completion_tokens == 5
    assert ctx.usage.total_tokens == 20
    assert ctx.usage.cost_usd == pytest.approx(0.03)


def test_sketch_and_condensation_take_the_latest_of_their_kind():
    managed = FakeManaged(
        [
            WorkspaceSketchEvent(content="first sketch"),
            CondensationEvent(summary="first summary", replaced_event_ids=[]),
            WorkspaceSketchEvent(content="second sketch"),
            CondensationEvent(summary="second summary", replaced_event_ids=[]),
        ]
    )

    ctx = service().context(managed)

    assert ctx.workspace_sketch is not None
    assert ctx.workspace_sketch.text == "second sketch"
    assert ctx.condensation is not None
    assert ctx.condensation.text == "second summary"


def test_absent_sections_are_none_rather_than_empty():
    ctx = service().context(FakeManaged([]))

    assert ctx.workspace_sketch is None
    assert ctx.condensation is None
    assert ctx.last_error is None
    assert ctx.usage.total_tokens == 0
    assert ctx.counts.events == 0


def test_last_error_carries_its_trace_id():
    managed = FakeManaged(
        [
            ErrorEvent(message="first failure", trace_id="a" * 32),
            ErrorEvent(message="latest failure", trace_id="b" * 32),
        ]
    )

    ctx = service().context(managed)

    assert ctx.last_error is not None
    assert ctx.last_error.message == "latest failure"
    assert ctx.last_error.trace_id == "b" * 32


def test_an_error_without_tracing_still_surfaces():
    managed = FakeManaged([ErrorEvent(message="boom", trace_id=None)])

    ctx = service().context(managed)

    assert ctx.last_error is not None
    assert ctx.last_error.trace_id is None


def test_user_turns_and_event_count():
    managed = FakeManaged(
        [
            MessageEvent(role="user", text="one"),
            MessageEvent(role="assistant", text="reply"),
            MessageEvent(role="user", text="two"),
        ]
    )

    ctx = service().context(managed)

    assert ctx.counts.user_turns == 2
    assert ctx.counts.events == 3


def test_a_conversation_without_a_repo_reports_nulls_not_errors():
    ctx = service().context(FakeManaged([], repo=None))

    assert ctx.repo is None
    assert ctx.branch is None
    assert ctx.session_changes.files == 0


def test_legacy_error_payloads_deserialise_without_a_trace_id():
    restored = ErrorEvent.model_validate(
        {"id": "e1", "timestamp": 1.0, "source": "environment", "kind": "error",
         "message": "old"}
    )
    assert restored.trace_id is None


class FakeContextService:
    def __init__(self, managed, owner: uuid.UUID) -> None:
        self.managed = managed
        self.owner = owner

    async def get_or_revive(self, cid: str, user_id: uuid.UUID):
        if cid != "c1" or user_id != self.owner:
            return None
        return self.managed

    def context(self, managed) -> ConversationContext:
        return ConversationService(
            manager=None, repository=None, connections=None
        ).context(managed)


@pytest.fixture
async def client(verifier, user_a, user_b):
    application = FastAPI()
    application.include_router(conversations_router)
    users = FakeUserRepository()
    owner = uuid.UUID(user_a.sub)
    await users.upsert(user_id=owner, email=None, avatar_url=None)
    await users.upsert(user_id=uuid.UUID(user_b.sub), email=None, avatar_url=None)

    managed = FakeManaged([WorkspaceSketchEvent(content="sketch")])
    application.state.verifier = verifier
    application.state.users = users
    application.state.connections = FakeConnectionRepository()
    application.state.service = FakeContextService(managed, owner)

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client


async def test_context_requires_authentication(client):
    assert (await client.get("/conversations/c1/context")).status_code == 401


async def test_context_rejects_a_garbage_token(client):
    response = await client.get(
        "/conversations/c1/context", headers={"Authorization": "Bearer nonsense"}
    )
    assert response.status_code == 401


async def test_context_hides_another_users_conversation(client):
    response = await client.get(
        "/conversations/c1/context", headers={"Authorization": "Bearer token-b"}
    )
    assert response.status_code == 404


async def test_context_returns_the_documented_shape(client):
    response = await client.get(
        "/conversations/c1/context", headers={"Authorization": "Bearer token-a"}
    )
    assert response.status_code == 200

    body = response.json()
    assert body["model"] == "gpt-4o-mini"
    assert body["status"] == "idle"
    assert body["workspace_sketch"]["text"] == "sketch"
    assert body["usage"]["total_tokens"] == 0
    assert body["last_error"] is None
    assert set(body) >= {
        "repo",
        "branch",
        "workspace_dir",
        "model",
        "status",
        "workspace_sketch",
        "condensation",
        "usage",
        "last_error",
        "session_changes",
        "counts",
    }
