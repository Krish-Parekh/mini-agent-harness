from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from backend.core.db import Base, make_engine, make_sessionmaker
from backend.repository import (
    ConversationRepository,
    GitHubConnectionRepository,
    UserRepository,
)

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://miniagent:miniagent@localhost:5432/miniagent",
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def sessionmaker():
    schema = f"test_{uuid.uuid4().hex[:8]}"
    engine = make_engine(DATABASE_URL).execution_options(
        schema_translate_map={None: schema}
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"no database available: {exc}")
    try:
        yield make_sessionmaker(engine)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


@pytest.fixture
async def repos(sessionmaker):
    users = UserRepository(sessionmaker)
    a = await users.upsert(user_id=uuid.uuid4(), email="a@x.com", avatar_url=None)
    b = await users.upsert(user_id=uuid.uuid4(), email="b@x.com", avatar_url=None)
    return (
        ConversationRepository(sessionmaker),
        GitHubConnectionRepository(sessionmaker),
        a.id,
        b.id,
    )


async def _make_conversation(repo: ConversationRepository, cid: str, owner: uuid.UUID):
    await repo.upsert_conversation(
        cid=cid,
        user_id=owner,
        repo="octocat/hello",
        branch="main",
        status="idle",
        title=None,
        workspace_dir="/tmp/ws",
        plan=None,
        implementing_plan=False,
    )


async def test_get_hides_another_users_conversation(repos):
    conversations, _, a, b = repos
    await _make_conversation(conversations, "c1", a)

    assert await conversations.get("c1", a) is not None
    assert await conversations.get("c1", b) is None


async def test_list_summaries_is_scoped(repos):
    conversations, _, a, b = repos
    await _make_conversation(conversations, "c-a", a)
    await _make_conversation(conversations, "c-b", b)

    assert [row.id for row, _ in await conversations.list_summaries(a)] == ["c-a"]
    assert [row.id for row, _ in await conversations.list_summaries(b)] == ["c-b"]


async def test_delete_is_scoped(repos):
    conversations, _, a, b = repos
    await _make_conversation(conversations, "c1", a)

    assert await conversations.delete("c1", b) is False
    assert await conversations.get("c1", a) is not None
    assert await conversations.delete("c1", a) is True


async def test_ownership_survives_an_event_upsert(repos):
    conversations, _, a, b = repos
    await _make_conversation(conversations, "c1", a)
    await conversations.record_event(
        cid="c1",
        user_id=a,
        repo="octocat/hello",
        branch="main",
        status="running",
        title="t",
        workspace_dir="/tmp/ws",
        plan=None,
        implementing_plan=False,
        event_id="e1",
        seq=1,
        source="user",
        kind="message",
        payload={"kind": "message", "text": "hi"},
    )

    row = await conversations.get("c1", a)
    assert row is not None and row.status == "running"
    assert await conversations.get("c1", b) is None


async def test_connection_roundtrip_and_delete(repos):
    _, connections, a, _ = repos
    await connections.upsert(
        user_id=a,
        github_user_id=42,
        login="octocat",
        avatar_url=None,
        access_token="gho_secret",
        scopes="repo",
    )

    assert await connections.token_for(a) == "gho_secret"
    assert await connections.delete(a) is True
    assert await connections.get(a) is None
    assert await connections.delete(a) is False
