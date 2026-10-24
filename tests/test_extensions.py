from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI
from types import SimpleNamespace

from backend.api.extensions import router as extensions_router
from backend.runtime.manager import ManagedConversation
from backend.models import McpConnectionRow, SkillRow
from backend.service.extension import (
    SKILL_CATALOG_BUDGET_CHARS,
    ImportError_,
    SkillService,
)
from miniagent import skills_registry
from miniagent.agent import Agent
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation, Status
from miniagent.events import ActionEvent
from miniagent.llm import LLMResponse, ToolCall
from miniagent.schema import Action
from miniagent.tools.base import Tool, ToolRegistry
from miniagent.tools.find_skills import (
    FindSkillsAction,
    FindSkillsTool,
    ProposeSkillsTool,
)
from miniagent.tools.finish import FinishTool
from miniagent.tools.mcp import McpTool, tool_name
from tests.context_snapshot import ScriptedLLM, SnapshotSandbox
from tests.fakes import FakeConnectionRepository, FakeUserRepository
from tests.test_sandbox_failures import SafePolicy


class FakeSkillRepository:
    def __init__(self) -> None:
        self.rows: dict[str, SkillRow] = {}
        self.enabled: dict[str, list[str]] = {}
        self.repos: list[tuple[uuid.UUID, str, str]] = []

    async def list_for_user(self, user_id):
        return [r for r in self.rows.values() if r.user_id == user_id]

    def add(self, user_id, name, description="", body="body", registry_id=None):
        row = SkillRow(
            id=uuid.uuid4().hex[:8],
            user_id=user_id,
            name=name,
            description=description,
            body=body,
            registry_id=registry_id,
        )
        self.rows[row.id] = row
        return row

    async def upsert_registry(self, *, user_id, registry_id, **fields):
        for row in self.rows.values():
            if row.user_id == user_id and row.registry_id == registry_id:
                for key, value in fields.items():
                    setattr(row, key, value)
                return row
        row = self.add(user_id, fields["name"], registry_id=registry_id)
        for key, value in fields.items():
            setattr(row, key, value)
        return row

    async def repos_by_skill(self, user_id):
        repos: dict[str, list[str]] = {}
        for owner, repo, skill_id in sorted(self.repos, key=lambda r: r[1]):
            if owner == user_id:
                repos.setdefault(skill_id, []).append(repo)
        return repos

    async def set_repo_enabled(self, user_id, repo, skill_id, enabled):
        key = (user_id, repo, skill_id)
        if enabled and key not in self.repos:
            self.repos.append(key)
        if not enabled and key in self.repos:
            self.repos.remove(key)

    async def get(self, skill_id, user_id):
        row = self.rows.get(skill_id)
        return row if row and row.user_id == user_id else None

    async def delete(self, skill_id, user_id):
        row = self.rows.get(skill_id)
        if row is None or row.user_id != user_id:
            return False
        del self.rows[skill_id]
        return True

    async def enabled_for_conversation(self, cid, user_id=None, repo=None):
        ids = list(self.enabled.get(cid, []))
        ids += [s for u, r, s in self.repos if u == user_id and r == repo]
        return [self.rows[i] for i in dict.fromkeys(ids) if i in self.rows]

    async def set_enabled(self, cid, skill_id, enabled):
        current = self.enabled.setdefault(cid, [])
        if enabled and skill_id not in current:
            current.append(skill_id)
        if not enabled and skill_id in current:
            current.remove(skill_id)


class FakeMcpRepository:
    def __init__(self) -> None:
        self.rows: dict[str, McpConnectionRow] = {}
        self.enabled: dict[str, list[str]] = {}

    async def list_for_user(self, user_id):
        return [r for r in self.rows.values() if r.user_id == user_id]

    async def create(self, *, user_id, name, url, auth_header, auth_value):
        row = McpConnectionRow(
            id=uuid.uuid4().hex[:8],
            user_id=user_id,
            name=name,
            url=url,
            auth_header=auth_header,
            auth_value=auth_value,
        )
        self.rows[row.id] = row
        return row

    async def get(self, connection_id, user_id):
        row = self.rows.get(connection_id)
        return row if row and row.user_id == user_id else None

    async def delete(self, connection_id, user_id):
        row = self.rows.get(connection_id)
        if row is None or row.user_id != user_id:
            return False
        del self.rows[connection_id]
        return True

    async def enabled_for_conversation(self, cid):
        return [self.rows[i] for i in self.enabled.get(cid, []) if i in self.rows]

    async def set_enabled(self, cid, connection_id, enabled):
        current = self.enabled.setdefault(cid, [])
        if enabled and connection_id not in current:
            current.append(connection_id)
        if not enabled and connection_id in current:
            current.remove(connection_id)


def skill(name: str, body: str) -> SkillRow:
    return SkillRow(
        id=name, user_id=uuid.uuid4(), name=name, description="", body=body
    )


SKILL_BODY = "---\nname: tdd\ndescription: Test first\n---\n# TDD"


def _github(tree, files, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        if request.url.host == "api.github.com":
            return httpx.Response(200, json={"tree": tree})
        path = request.url.path.split("/HEAD/", 1)[1]
        if path not in files:
            return httpx.Response(404, text="missing")
        return httpx.Response(200, text=files[path], headers={"content-type": "text/plain"})

    return httpx.MockTransport(handler)


def _blobs(*paths):
    return [{"path": p, "type": "blob"} for p in paths]


def _install_service(transport, repo=None, connections=None):
    return SkillService(repo or FakeSkillRepository(), connections, transport=transport)


async def test_install_resolves_the_skill_folder_and_enables_it_for_the_repo():
    repo = FakeSkillRepository()
    connections = FakeConnectionRepository()
    user_id = uuid.uuid4()
    await connections.upsert(
        user_id=user_id, github_user_id=1, login="me", avatar_url=None,
        access_token="gho_secret", scopes=None,
    )
    seen: list = []
    transport = _github(
        _blobs("README.md", "skills/engineering/tdd/SKILL.md", "skills/misc/x/SKILL.md"),
        {"skills/engineering/tdd/SKILL.md": SKILL_BODY},
        seen,
    )
    row = await _install_service(transport, repo, connections).install(
        user_id, "mattpocock/skills", "tdd", "acme/app"
    )

    assert row.name == "tdd"
    assert row.description == "Test first"
    assert row.body == SKILL_BODY
    assert row.registry_id == "mattpocock/skills/tdd"
    assert row.source_url == "https://skills.sh/mattpocock/skills/tdd"
    assert await repo.repos_by_skill(user_id) == {row.id: ["acme/app"]}
    assert seen[0].headers["authorization"] == "Bearer gho_secret"
    assert seen[1].url.path == "/mattpocock/skills/HEAD/skills/engineering/tdd/SKILL.md"


async def test_reinstalling_reuses_the_row_and_adds_the_repo():
    repo = FakeSkillRepository()
    user_id = uuid.uuid4()
    transport = _github(_blobs("tdd/SKILL.md"), {"tdd/SKILL.md": SKILL_BODY})
    first = await _install_service(transport, repo).install(user_id, "o/r", "tdd", "acme/a")
    second = await _install_service(transport, repo).install(user_id, "o/r", "tdd", "acme/b")

    assert first.id == second.id and len(repo.rows) == 1
    assert (await repo.repos_by_skill(user_id))[first.id] == ["acme/a", "acme/b"]


async def test_install_falls_back_to_the_frontmatter_name():
    body = "---\nname: vercel-react-best-practices\n---\nbody"
    transport = _github(
        _blobs("skills/deploy/SKILL.md", "skills/react-best-practices/SKILL.md"),
        {
            "skills/deploy/SKILL.md": "---\nname: deploy\n---\n",
            "skills/react-best-practices/SKILL.md": body,
        },
    )
    row = await _install_service(transport).install(
        uuid.uuid4(), "vercel-labs/agent-skills", "vercel-react-best-practices", "a/b"
    )
    assert row.name == "vercel-react-best-practices"
    assert row.body == body


async def test_install_reports_a_missing_skill():
    transport = _github(_blobs("other/SKILL.md"), {"other/SKILL.md": "---\nname: other\n---"})
    with pytest.raises(ImportError_, match="Couldn't find SKILL.md for tdd in o/r"):
        await _install_service(transport).install(uuid.uuid4(), "o/r", "tdd", "a/b")


async def test_install_keeps_the_size_cap():
    transport = _github(_blobs("tdd/SKILL.md"), {"tdd/SKILL.md": "x" * (256 * 1024 + 1)})
    with pytest.raises(ImportError_, match="256 KB"):
        await _install_service(transport).install(uuid.uuid4(), "o/r", "tdd", "a/b")


@pytest.mark.parametrize(
    "source,skill_id,repo",
    [("../etc", "tdd", "a/b"), ("o/r", "../x", "a/b"), ("o/r", "tdd", "not-a-repo")],
)
async def test_install_rejects_malformed_names(source, skill_id, repo):
    transport = _github([], {})
    with pytest.raises(ImportError_):
        await _install_service(transport).install(uuid.uuid4(), source, skill_id, repo)


async def test_a_name_clash_with_another_source_uses_the_registry_id():
    repo = FakeSkillRepository()
    user_id = uuid.uuid4()
    repo.add(user_id, "tdd", registry_id="someone/else/tdd")
    transport = _github(_blobs("tdd/SKILL.md"), {"tdd/SKILL.md": SKILL_BODY})
    row = await _install_service(transport, repo).install(user_id, "o/r", "tdd", "a/b")
    assert row.name == "o/r/tdd"


def test_registry_search_reads_descriptions_from_skill_pages():
    def handler(request):
        if request.url.path == "/api/search":
            assert request.url.params["q"] == "react"
            return httpx.Response(
                200,
                json={
                    "skills": [
                        {"id": "o/r/a", "source": "o/r", "skillId": "a", "name": "a", "installs": 5},
                        {"id": "o/r/b", "source": "o/r", "skillId": "b", "name": "b", "installs": 1},
                        {"id": "o/r/c", "source": "o/r", "skillId": "c", "name": "c", "installs": 0},
                    ]
                },
            )
        if request.url.host == "skills.sh":
            return httpx.Response(308, headers={"location": f"https://www.skills.sh{request.url.path}"})
        if request.url.path == "/o/r/a":
            return httpx.Response(
                200, text='<head><meta name="description" content="Use &quot;A&quot; well"/></head>'
            )
        return httpx.Response(500)

    hits = skills_registry.search("react", limit=2, transport=httpx.MockTransport(handler))
    assert [(h.id, h.source, h.skill_id, h.installs, h.description) for h in hits] == [
        ("o/r/a", "o/r", "a", 5, 'Use "A" well'),
        ("o/r/b", "o/r", "b", 1, ""),
    ]


def test_registry_search_failure_raises():
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    with pytest.raises(skills_registry.RegistryError):
        skills_registry.search("x", transport=transport)


class _PlainAction(Action):
    value: int


class _PlainTool(Tool):
    name = "plain"
    description = "plain"
    action_type = _PlainAction
    observation_type = Action

    def execute(self, action, sandbox):
        raise NotImplementedError


def test_mcp_tools_are_risky_under_the_confirm_policy():
    policy = ConfirmPolicy("auto")
    call = ActionEvent(
        tool_name=tool_name("linear", "create_issue"), arguments={}, tool_call_id="1"
    )
    assert policy.needs_confirmation(call)


def _host():
    events: list = []
    agent = SimpleNamespace(
        skills_block="", mcp_instructions={}, tools=ToolRegistry([_PlainTool()])
    )
    conversation = SimpleNamespace(agent=agent, add_event=events.append)
    host = SimpleNamespace(
        conversation=conversation, mcp_tools={}, mcp_skipped=set(), mcp_instructions={}
    )
    return host, events


def _apply(host, targets, skills_block="", skill_bodies=None):
    ManagedConversation.apply_extensions(host, skills_block, skill_bodies or {}, targets)


class FakeService:
    def __init__(self) -> None:
        self.conversations: dict[str, SimpleNamespace] = {}

    def add(self, cid, user_id, repo=None):
        self.conversations[cid] = SimpleNamespace(
            conversation=SimpleNamespace(id=cid),
            user_id=user_id,
            repo=repo,
            mcp_skipped=set(),
        )

    async def get_or_revive(self, cid, user_id):
        managed = self.conversations.get(cid)
        return managed if managed and managed.user_id == user_id else None


@pytest.fixture
async def client(verifier, user_a, user_b):
    application = FastAPI()
    application.include_router(extensions_router)
    users = FakeUserRepository()
    await users.upsert(user_id=uuid.UUID(user_a.sub), email=None, avatar_url=None)
    await users.upsert(user_id=uuid.UUID(user_b.sub), email=None, avatar_url=None)

    application.state.verifier = verifier
    application.state.users = users
    application.state.connections = FakeConnectionRepository()
    application.state.skills = FakeSkillRepository()
    application.state.mcp_connections = FakeMcpRepository()
    application.state.service = FakeService()

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/skills"),
        ("get", "/skills/search?q=react"),
        ("post", "/skills/install"),
        ("put", "/skills/abc/repos"),
        ("get", "/mcp/connections"),
        ("post", "/mcp/connections"),
    ],
)
async def test_extension_routes_require_authentication(client, method, path):
    kwargs = {"json": {}} if method in ("post", "put") else {}
    response = await getattr(client, method)(path, **kwargs)
    assert response.status_code == 401


def _skills(client) -> FakeSkillRepository:
    return client._transport.app.state.skills


async def test_skills_are_scoped_to_their_owner(client, user_a):
    created = _skills(client).add(uuid.UUID(user_a.sub), "mine")

    assert [s["name"] for s in (await client.get("/skills", headers=bearer("token-a"))).json()] == ["mine"]
    assert (await client.get("/skills", headers=bearer("token-b"))).json() == []

    foreign = await client.delete(f"/skills/{created.id}", headers=bearer("token-b"))
    assert foreign.status_code == 404
    foreign = await client.put(
        f"/skills/{created.id}/repos",
        json={"repo": "acme/app", "enabled": True},
        headers=bearer("token-b"),
    )
    assert foreign.status_code == 404


async def test_removed_skill_authoring_routes_are_gone(client):
    for path in ("/skills", "/skills/import"):
        response = await client.post(path, json={}, headers=bearer("token-a"))
        assert response.status_code == 405


async def test_skill_repos_round_trip(client, user_a):
    row = _skills(client).add(uuid.UUID(user_a.sub), "tdd", registry_id="o/r/tdd")
    path = f"/skills/{row.id}/repos"
    for repo in ("acme/web", "acme/api"):
        response = await client.put(
            path, json={"repo": repo, "enabled": True}, headers=bearer("token-a")
        )
    assert response.status_code == 200
    assert response.json()["repos"] == ["acme/api", "acme/web"]
    assert response.json()["registry_id"] == "o/r/tdd"

    await client.put(path, json={"repo": "acme/web", "enabled": False}, headers=bearer("token-a"))
    [listed] = (await client.get("/skills", headers=bearer("token-a"))).json()
    assert listed["repos"] == ["acme/api"]


async def test_search_route_returns_hits(client, monkeypatch):
    hit = skills_registry.SkillHit(
        id="o/r/tdd", source="o/r", skill_id="tdd", name="tdd", installs=3, description="d"
    )
    monkeypatch.setattr(skills_registry, "search", lambda q: [hit] if q == "tdd" else [])
    response = await client.get("/skills/search", params={"q": "tdd"}, headers=bearer("token-a"))
    assert response.json() == [hit.model_dump()]
    too_long = await client.get("/skills/search", params={"q": "x" * 101}, headers=bearer("token-a"))
    assert too_long.status_code == 422


async def test_install_route_reports_failures_as_400(client):
    response = await client.post(
        "/skills/install",
        json={"source": "o/r", "skill_id": "tdd", "repo": "bad"},
        headers=bearer("token-a"),
    )
    assert response.status_code == 400
    assert "owner/name" in response.json()["detail"]


async def test_repo_skills_join_the_conversation_catalog(client, user_a):
    owner = uuid.UUID(user_a.sub)
    client._transport.app.state.service.add("conv-a", owner, repo="acme/app")
    repo = _skills(client)
    project = repo.add(owner, "project-skill")
    chat = repo.add(owner, "chat-skill")
    elsewhere = repo.add(owner, "other-skill")
    await repo.set_repo_enabled(owner, "acme/app", project.id, True)
    await repo.set_repo_enabled(owner, "acme/other", elsewhere.id, True)
    await repo.set_enabled("conv-a", chat.id, True)
    await repo.set_enabled("conv-a", project.id, True)

    included, skipped = await SkillService(repo).enabled_catalog("conv-a", owner, "acme/app")
    assert [s.name for s in included] == ["chat-skill", "project-skill"] and skipped == []
    listed = (await client.get("/conversations/conv-a/skills", headers=bearer("token-a"))).json()
    assert {i["name"]: i["enabled"] for i in listed} == {
        "project-skill": True, "chat-skill": True, "other-skill": False,
    }


async def test_mcp_connection_never_returns_its_credential(client):
    created = await client.post(
        "/mcp/connections",
        json={
            "name": "probe",
            "url": "https://mcp.example.com/mcp",
            "auth_header": "Authorization",
            "auth_value": "Bearer super-secret-value",
        },
        headers=bearer("token-a"),
    )
    assert created.status_code == 200
    assert "super-secret-value" not in created.text

    listed = await client.get("/mcp/connections", headers=bearer("token-a"))
    assert "super-secret-value" not in listed.text
    assert listed.json()[0]["auth_header"] == "Authorization"


async def test_mcp_connection_rejects_plain_http(client):
    response = await client.post(
        "/mcp/connections",
        json={"name": "bad", "url": "http://mcp.example.com/mcp"},
        headers=bearer("token-a"),
    )
    assert response.status_code == 400


async def test_mcp_connections_are_scoped_to_their_owner(client):
    created = await client.post(
        "/mcp/connections",
        json={"name": "mine", "url": "https://mcp.example.com/mcp"},
        headers=bearer("token-a"),
    )
    assert (await client.get("/mcp/connections", headers=bearer("token-b"))).json() == []
    foreign = await client.delete(
        f"/mcp/connections/{created.json()['id']}", headers=bearer("token-b")
    )
    assert foreign.status_code == 404


async def test_enabling_a_skill_round_trips(client, user_a):
    client._transport.app.state.service.add("conv-a", uuid.UUID(user_a.sub))
    created = {"id": _skills(client).add(uuid.UUID(user_a.sub), "review").id}

    path = f"/conversations/conv-a/skills/{created['id']}"
    assert (await client.put(path, json={"enabled": True}, headers=bearer("token-a"))).json()["enabled"]
    listed = (await client.get("/conversations/conv-a/skills", headers=bearer("token-a"))).json()
    assert listed == [{"id": created["id"], "name": "review", "enabled": True, "skipped": False}]

    await client.put(path, json={"enabled": False}, headers=bearer("token-a"))
    listed = (await client.get("/conversations/conv-a/skills", headers=bearer("token-a"))).json()
    assert listed[0]["enabled"] is False
    assert len((await client.get("/skills", headers=bearer("token-a"))).json()) == 1


async def test_an_over_budget_skill_is_flagged_skipped(client, user_a):
    client._transport.app.state.service.add("conv-a", uuid.UUID(user_a.sub))
    for name, size in (("small", 10), ("huge", SKILL_CATALOG_BUDGET_CHARS)):
        row = _skills(client).add(uuid.UUID(user_a.sub), name, "d" * size)
        await client.put(
            f"/conversations/conv-a/skills/{row.id}",
            json={"enabled": True},
            headers=bearer("token-a"),
        )
    listed = (await client.get("/conversations/conv-a/skills", headers=bearer("token-a"))).json()
    assert {i["name"]: i["skipped"] for i in listed} == {"small": False, "huge": True}


async def test_a_foreign_conversation_or_extension_is_404(client, user_a, user_b):
    service = client._transport.app.state.service
    service.add("conv-a", uuid.UUID(user_a.sub))
    service.add("conv-b", uuid.UUID(user_b.sub))
    skill_b = {"id": _skills(client).add(uuid.UUID(user_b.sub), "b").id}
    mcp_b = (
        await client.post(
            "/mcp/connections",
            json={"name": "b", "url": "https://mcp.example.com/mcp"},
            headers=bearer("token-b"),
        )
    ).json()

    for path in ("/conversations/conv-b/skills", "/conversations/conv-b/mcp"):
        assert (await client.get(path, headers=bearer("token-a"))).status_code == 404
    for path in (
        f"/conversations/conv-a/skills/{skill_b['id']}",
        f"/conversations/conv-a/mcp/{mcp_b['id']}",
    ):
        response = await client.put(path, json={"enabled": True}, headers=bearer("token-a"))
        assert response.status_code == 404
    response = await client.post(
        f"/mcp/connections/{mcp_b['id']}/test", headers=bearer("token-a")
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "url",
    ["http://127.evil.example.com/mcp", "http://example.com/mcp", "ftp://localhost/mcp"],
)
async def test_mcp_connection_rejects_non_local_plain_urls(client, url):
    response = await client.post(
        "/mcp/connections", json={"name": "x", "url": url}, headers=bearer("token-a")
    )
    assert response.status_code == 400


def _mcp_agent():
    def remote(name, read_only):
        return McpTool(
            connection="linear",
            remote_name=name,
            description="",
            input_schema={},
            invoke=lambda n, a: "",
            read_only=read_only,
        )

    tools = ToolRegistry([remote("search", True), remote("create_issue", False)])
    agent = Agent(llm=SimpleNamespace(model="m"), tools=tools, policy=object())
    policy = ConfirmPolicy("auto")
    conversation = SimpleNamespace(
        confirm_policy=policy, needs_confirmation=policy.needs_confirmation
    )
    return agent, conversation


def _call(name):
    return ActionEvent(tool_name=tool_name("linear", name), arguments={}, tool_call_id="1")


def test_read_only_mcp_tools_run_without_confirmation():
    agent, conversation = _mcp_agent()
    assert not agent._needs_confirmation(_call("search"), conversation)
    assert agent._needs_confirmation(_call("create_issue"), conversation)


def test_plan_mode_allows_mcp_reads_and_blocks_writes():
    agent, _ = _mcp_agent()
    assert not agent._mutates(_call("search"))
    assert agent._mutates(_call("create_issue"))


def test_enabled_skills_register_the_skill_tool_and_disable_removes_it():
    host, _ = _host()
    _apply(host, {}, skills_block="- review: be thorough", skill_bodies={"review": "BODY"})
    tools = host.conversation.agent.tools
    assert "skill" in tools
    assert tools["skill"].execute(tools["skill"].action_type(name="review"), None).content == "BODY"
    unknown = tools["skill"].execute(tools["skill"].action_type(name="nope"), None)
    assert unknown.error and "review" in unknown.content

    _apply(host, {})
    assert "skill" not in host.conversation.agent.tools
    assert host.conversation.agent.skills_block == ""


def test_skill_description_comes_from_frontmatter():
    from backend.service.extension import describe_skill

    body = "---\nname: review\ndescription: Review a PR for bugs\n---\n# Review\nSteps..."
    assert describe_skill(body) == "Review a PR for bugs"


def test_find_skills_lists_hits_and_reports_errors(monkeypatch):
    hit = skills_registry.SkillHit(
        id="o/r/tdd", source="o/r", skill_id="tdd", name="tdd", installs=7, description="Test first"
    )
    monkeypatch.setattr(skills_registry, "search", lambda q: [hit])
    observation = FindSkillsTool().execute(FindSkillsAction(query="tdd"), None)
    assert observation.to_llm_text() == "- o/r/tdd (7 installs): Test first"
    assert observation.ui_details()["hits"][0]["skill_id"] == "tdd"

    def fail(q):
        raise skills_registry.RegistryError("skills.sh search failed: boom")

    monkeypatch.setattr(skills_registry, "search", fail)
    observation = FindSkillsTool().execute(FindSkillsAction(query="tdd"), None)
    assert observation.error and observation.to_llm_text().startswith("ERROR:")


def test_propose_skills_pauses_the_turn():
    llm = ScriptedLLM()
    agent = Agent(
        llm=llm,
        tools=ToolRegistry([ProposeSkillsTool(), FinishTool()]),
        policy=SafePolicy(),
    )
    conversation = Conversation(
        agent=agent,
        sandbox=SnapshotSandbox(),
        confirm_policy=ConfirmPolicy("full"),
        stuck_detection=False,
    )
    proposal = {
        "skills": [{"source": "o/r", "skill_id": "tdd", "name": "tdd", "installs": 3}],
        "reason": "The project needs tests.",
    }
    llm.responses.append(
        LLMResponse(tool_calls=[ToolCall(id="c1", name="propose_skills", arguments=proposal)])
    )
    conversation.send_message("/find-skill testing")
    conversation.run()

    assert conversation.status == Status.IDLE
    assert llm.responses == [] and len(llm.seen) == 1
    assert conversation.events[-1].content.startswith("Proposed skills to the user.")
