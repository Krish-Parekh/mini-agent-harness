from __future__ import annotations

import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from backend.api.conversations import router as conversations_router
from backend.api.github import router as github_router
from backend.api.sandbox import router as sandbox_router
from backend.schemas import ConversationInfo
from backend.service import AuthService
from miniagent.config import Settings
from tests.fakes import FakeConnectionRepository, FakeConversationService, FakeUserRepository
from tests.test_auth_api import _stub_identity, bearer
from tests.test_extensions import FakeSkillRepository


class RecordingService(FakeConversationService):
    def __init__(self) -> None:
        super().__init__()
        self.created: list[dict] = []

    def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id="new")

    def info(self, managed):
        return ConversationInfo(id="new", status="idle", workspace_dir="/w", num_events=0)


@pytest.fixture
def app(verifier, monkeypatch) -> FastAPI:
    for name in ("E2B_API_KEY", "MINIAGENT_SANDBOX_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    application = FastAPI()
    for router in (conversations_router, github_router, sandbox_router):
        application.include_router(router)
    users = FakeUserRepository()
    connections = FakeConnectionRepository()
    application.state.verifier = verifier
    application.state.users = users
    application.state.connections = connections
    application.state.service = RecordingService()
    application.state.auth_service = AuthService(users, connections)
    application.state.settings = Settings(_env_file=None)
    application.state.skills = FakeSkillRepository()
    return application


@pytest.fixture
async def client(app):
    from backend.api.auth import router as auth_router

    app.include_router(auth_router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post("/auth/sync", json={}, headers=bearer("token-a"))
        yield c


def _docker(monkeypatch, problem):
    monkeypatch.setattr("miniagent.sandbox.docker.docker_problem", lambda image: problem)


async def test_providers_default_to_docker_when_it_is_running(client, monkeypatch):
    _docker(monkeypatch, None)
    resp = await client.get("/sandbox/providers", headers=bearer("token-a"))
    providers = {p["id"]: p for p in resp.json()}
    assert providers["docker"]["available"] and providers["docker"]["default"]
    assert providers["local"]["available"] and not providers["local"]["default"]
    assert providers["e2b"]["available"] is False
    assert "E2B_API_KEY" in providers["e2b"]["reason"]


async def test_providers_fall_back_to_local_when_docker_is_down(client, monkeypatch):
    _docker(monkeypatch, "Docker is not running")
    resp = await client.get("/sandbox/providers", headers=bearer("token-a"))
    providers = {p["id"]: p for p in resp.json()}
    assert providers["docker"]["available"] is False
    assert providers["docker"]["reason"] == "Docker is not running"
    assert not providers["docker"]["default"]
    assert providers["local"]["default"]


async def test_create_without_a_provider_uses_the_effective_default(client, app, monkeypatch):
    _docker(monkeypatch, "Docker is not running")
    resp = await client.post("/conversations", json={"repo": "o/r"}, headers=bearer("token-a"))
    assert resp.status_code == 200
    assert app.state.service.created[-1]["sandbox_provider"] == "local"


async def test_create_rejects_docker_when_it_is_down(client, app, monkeypatch):
    _docker(monkeypatch, "Docker is not running")
    resp = await client.post(
        "/conversations",
        json={"repo": "o/r", "sandbox_provider": "docker"},
        headers=bearer("token-a"),
    )
    assert resp.status_code == 400
    assert app.state.service.created == []


async def test_providers_require_auth(client):
    assert (await client.get("/sandbox/providers")).status_code == 401


async def test_create_rejects_an_unavailable_provider(client, app):
    resp = await client.post(
        "/conversations",
        json={"repo": "o/r", "sandbox_provider": "e2b"},
        headers=bearer("token-a"),
    )
    assert resp.status_code == 400
    assert app.state.service.created == []


async def test_create_rejects_a_foreign_skill(client, app, user_b):
    foreign = app.state.skills.add(uuid.UUID(user_b.sub), "x")
    resp = await client.post(
        "/conversations", json={"skill_ids": [foreign.id]}, headers=bearer("token-a")
    )
    assert resp.status_code == 404


async def test_create_passes_model_provider_and_skills(client, app, user_a):
    own = app.state.skills.add(uuid.UUID(user_a.sub), "mine")
    resp = await client.post(
        "/conversations",
        json={
            "repo": "o/r",
            "branch": "dev",
            "initial_message": "hi",
            "model": "anthropic/claude-opus-5-5",
            "sandbox_provider": "local",
            "skill_ids": [own.id],
        },
        headers=bearer("token-a"),
    )
    assert resp.status_code == 200
    [created] = app.state.service.created
    assert created["model"] == "anthropic/claude-opus-5-5"
    assert created["sandbox_provider"] == "local"
    assert created["skill_ids"] == [own.id]
    assert created["branch"] == "dev"


def _github(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr("backend.api.github.httpx.AsyncClient", factory)


async def _connect(client, monkeypatch):
    monkeypatch.setattr(
        "backend.service.auth._fetch_github_identity", _stub_identity(login="octocat")
    )
    await client.post("/auth/sync", json={"provider_token": "gho_x"}, headers=bearer("token-a"))


async def test_branches_put_the_default_first(client, monkeypatch):
    await _connect(client, monkeypatch)

    def handler(request):
        if request.url.path.endswith("/branches"):
            return httpx.Response(200, json=[{"name": n} for n in ("zeta", "main", "alpha")])
        return httpx.Response(200, json={"default_branch": "main"})

    _github(monkeypatch, handler)
    resp = await client.get("/auth/github/repos/o/r/branches", headers=bearer("token-a"))
    assert resp.json() == [
        {"name": "main", "default": True},
        {"name": "alpha", "default": False},
        {"name": "zeta", "default": False},
    ]


async def test_branches_of_an_invisible_repo_are_404(client, monkeypatch):
    await _connect(client, monkeypatch)
    _github(monkeypatch, lambda request: httpx.Response(404, json={}))
    resp = await client.get("/auth/github/repos/o/secret/branches", headers=bearer("token-a"))
    assert resp.status_code == 404


class _Run:
    def __init__(self, managed) -> None:
        self.managed = managed
        self.seen: dict = {}

    def __call__(self) -> None:
        self.seen = {
            "model": self.managed.conversation.agent.llm.model,
            "skills": dict(self.managed.applied_bodies),
        }


class _Managed:
    def __init__(self) -> None:
        import asyncio

        from miniagent.conversation import Status

        self.user_id = uuid.uuid4()
        self.repo = "o/r"
        self.branch = "main"
        self.title = None
        self.lock = asyncio.Lock()
        self.skills_skipped: set[str] = set()
        self.queue: list = []
        self.applied_bodies: dict[str, str] = {}
        self.sandbox = SimpleNamespace(workspace_dir="/w", provider="local", sandbox_id=None)
        self.host_workspace = Path(self.sandbox.workspace_dir)
        self.broker = SimpleNamespace(publish=lambda update: None)
        self.run = _Run(self)
        self.conversation = SimpleNamespace(
            id="c1",
            status=Status.IDLE,
            events=[],
            live_events=lambda: [],
            cancel_event=threading.Event(),
            has_steering=lambda: False,
            plan=None,
            implementing_plan=False,
            agent=SimpleNamespace(llm=SimpleNamespace(model="default")),
            send_message=lambda text, attachments=None: None,
            run=self.run,
            add_event=lambda event: None,
        )

    def set_model(self, model: str) -> None:
        self.conversation.agent.llm.model = model

    def bootstrap(self) -> None:
        pass

    def apply_extensions(self, block, bodies, targets) -> None:
        self.applied_bodies = bodies


class _Rows:
    async def upsert_conversation(self, **fields) -> None:
        pass


async def test_the_first_run_sees_the_chosen_model_and_skills():
    import asyncio

    from backend.service import ConversationService
    from tests.test_extensions import FakeMcpRepository

    managed = _Managed()
    skills = FakeSkillRepository()
    row = skills.add(managed.user_id, "review", body="B")
    manager = SimpleNamespace(create=lambda **kwargs: managed)
    service = ConversationService(
        manager=manager,
        repository=_Rows(),
        connections=None,
        skills=skills,
        mcp=FakeMcpRepository(),
    )

    service.create(
        user_id=managed.user_id,
        repo="o/r",
        branch="main",
        workspace_dir=None,
        confirm_mode="risky",
        token=None,
        initial_message="go",
        model="anthropic/claude-opus-5-5",
        skill_ids=[row.id],
    )
    await asyncio.gather(*service._tasks)

    assert managed.run.seen == {"model": "anthropic/claude-opus-5-5", "skills": {"review": "B"}}


async def test_branches_require_auth(client):
    assert (await client.get("/auth/github/repos/o/r/branches")).status_code == 401


def test_a_short_first_line_is_the_title_as_is():
    from backend.runtime.manager import title_snippet

    assert title_snippet("  How are you?\nmore detail") == "How are you?"
