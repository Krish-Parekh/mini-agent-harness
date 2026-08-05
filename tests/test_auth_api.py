from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI

from backend.api.auth import router as auth_router
from backend.api.conversations import router as conversations_router
from backend.api.github import router as github_router
from backend.service import AuthService
from tests.fakes import (
    FakeConnectionRepository,
    FakeConversationService,
    FakeUserRepository,
)


@pytest.fixture
def app(verifier) -> FastAPI:
    application = FastAPI()
    application.include_router(conversations_router)
    application.include_router(auth_router)
    application.include_router(github_router)

    users = FakeUserRepository()
    connections = FakeConnectionRepository()
    application.state.verifier = verifier
    application.state.users = users
    application.state.connections = connections
    application.state.service = FakeConversationService()
    application.state.auth_service = AuthService(users, connections)
    return application


@pytest.fixture
async def client(app: FastAPI):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def sign_in(client: httpx.AsyncClient, token: str) -> dict:
    resp = await client.post("/auth/sync", json={}, headers=bearer(token))
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/conversations"),
        ("post", "/conversations"),
        ("get", "/conversations/abc"),
        ("delete", "/conversations/abc"),
        ("get", "/auth/me"),
        ("get", "/auth/github/repos"),
    ],
)
async def test_requires_a_token(client: httpx.AsyncClient, method: str, path: str):
    resp = await getattr(client, method)(path)
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


async def test_rejects_unknown_token(client: httpx.AsyncClient):
    resp = await client.get("/conversations", headers=bearer("garbage"))
    assert resp.status_code == 401


async def test_valid_token_without_a_synced_user_is_unauthenticated(
    client: httpx.AsyncClient,
):
    resp = await client.get("/conversations", headers=bearer("token-a"))
    assert resp.status_code == 401


async def test_sync_creates_the_user(client: httpx.AsyncClient, app, user_a):
    body = await sign_in(client, "token-a")
    assert body["user"]["id"] == user_a.sub
    assert body["user"]["email"] == "a@example.com"
    assert body["github"]["connected"] is False
    assert uuid.UUID(user_a.sub) in app.state.users.rows


async def test_sync_is_idempotent(client: httpx.AsyncClient, app):
    await sign_in(client, "token-a")
    await sign_in(client, "token-a")
    assert len(app.state.users.rows) == 1


async def test_sync_stores_a_valid_provider_token(
    client: httpx.AsyncClient, app, user_a, monkeypatch
):
    monkeypatch.setattr(
        "backend.service.auth._fetch_github_identity",
        _stub_identity(login="octocat"),
    )
    resp = await client.post(
        "/auth/sync", json={"provider_token": "gho_valid"}, headers=bearer("token-a")
    )
    assert resp.status_code == 200
    assert resp.json()["github"] == {
        "connected": True,
        "login": "octocat",
        "avatar_url": "https://avatars/octocat.png",
        "connected_at": None,
    }
    assert app.state.connections.rows[uuid.UUID(user_a.sub)].access_token == "gho_valid"


async def test_sync_with_a_rejected_provider_token_still_signs_in(
    client: httpx.AsyncClient, app, user_a, monkeypatch
):
    monkeypatch.setattr(
        "backend.service.auth._fetch_github_identity", _stub_identity(None)
    )
    resp = await client.post(
        "/auth/sync", json={"provider_token": "gho_revoked"}, headers=bearer("token-a")
    )
    assert resp.status_code == 200
    assert resp.json()["github"]["connected"] is False
    assert uuid.UUID(user_a.sub) in app.state.users.rows
    assert app.state.connections.rows == {}


async def test_no_response_leaks_the_access_token(
    client: httpx.AsyncClient, monkeypatch
):
    monkeypatch.setattr(
        "backend.service.auth._fetch_github_identity", _stub_identity(login="octocat")
    )
    sync = await client.post(
        "/auth/sync", json={"provider_token": "gho_secret"}, headers=bearer("token-a")
    )
    me = await client.get("/auth/me", headers=bearer("token-a"))
    assert "gho_secret" not in sync.text
    assert "gho_secret" not in me.text
    assert "access_token" not in sync.text


async def test_disconnect_drops_the_connection_but_keeps_the_user(
    client: httpx.AsyncClient, app, user_a, monkeypatch
):
    monkeypatch.setattr(
        "backend.service.auth._fetch_github_identity", _stub_identity(login="octocat")
    )
    await client.post(
        "/auth/sync", json={"provider_token": "gho_valid"}, headers=bearer("token-a")
    )

    resp = await client.post("/auth/github/disconnect", headers=bearer("token-a"))
    assert resp.status_code == 200
    assert resp.json() == {"connected": False}

    me = await client.get("/auth/me", headers=bearer("token-a"))
    assert me.json()["github"]["connected"] is False
    assert me.json()["user"]["id"] == user_a.sub
    assert uuid.UUID(user_a.sub) in app.state.users.rows


async def test_repos_requires_a_connection(client: httpx.AsyncClient):
    await sign_in(client, "token-a")
    resp = await client.get("/auth/github/repos", headers=bearer("token-a"))
    assert resp.status_code == 401
    assert resp.json()["detail"] == "GitHub is not connected"


async def test_a_cannot_read_or_delete_bs_conversation(
    client: httpx.AsyncClient, app, user_b
):
    await sign_in(client, "token-a")
    await sign_in(client, "token-b")
    app.state.service.add("b-conv", uuid.UUID(user_b.sub))

    read = await client.get("/conversations/b-conv", headers=bearer("token-a"))
    assert read.status_code == 404

    events = await client.get("/conversations/b-conv/events", headers=bearer("token-a"))
    assert events.status_code == 404

    removed = await client.delete("/conversations/b-conv", headers=bearer("token-a"))
    assert removed.status_code == 404
    assert "b-conv" in app.state.service.conversations


async def test_list_only_returns_your_own(client: httpx.AsyncClient, app, user_a, user_b):
    await sign_in(client, "token-a")
    await sign_in(client, "token-b")
    app.state.service.add("a-conv", uuid.UUID(user_a.sub))
    app.state.service.add("b-conv", uuid.UUID(user_b.sub))

    resp = await client.get("/conversations", headers=bearer("token-a"))
    assert [c["id"] for c in resp.json()] == ["a-conv"]


async def test_owner_can_delete_their_own(client: httpx.AsyncClient, app, user_a):
    await sign_in(client, "token-a")
    app.state.service.add("a-conv", uuid.UUID(user_a.sub))

    resp = await client.delete("/conversations/a-conv", headers=bearer("token-a"))
    assert resp.status_code == 200
    assert "a-conv" not in app.state.service.conversations


def _stub_identity(identity=..., *, login: str | None = None):
    from backend.service.auth import _GitHubIdentity

    if login is not None:
        identity = _GitHubIdentity(
            github_user_id=1,
            login=login,
            avatar_url=f"https://avatars/{login}.png",
            scopes="repo",
        )

    async def _stub(token: str):
        return identity

    return _stub
