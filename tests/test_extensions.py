from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI
from types import SimpleNamespace

from backend.api.extensions import router as extensions_router
from backend.runtime import manager as runtime_manager
from backend.runtime import mcp as mcp_client
from backend.runtime.manager import ManagedConversation
from backend.models import McpConnectionRow, SkillRow
from backend.service.extension import (
    SKILL_BUDGET_CHARS,
    ImportError_,
    SkillService,
    render_skills,
)
from miniagent.confirm import ConfirmPolicy
from miniagent.events import ActionEvent, ErrorEvent
from miniagent.schema import Action
from miniagent.tools.base import Tool, ToolRegistry, to_openai_schema
from miniagent.tools.mcp import MAX_TOOLS, McpTool, tool_name
from tests.fakes import FakeConnectionRepository, FakeUserRepository


class FakeSkillRepository:
    def __init__(self) -> None:
        self.rows: dict[str, SkillRow] = {}
        self.enabled: dict[str, list[str]] = {}

    async def list_for_user(self, user_id):
        return [r for r in self.rows.values() if r.user_id == user_id]

    async def create(self, *, user_id, name, description, body, source_url=None):
        row = SkillRow(
            id=uuid.uuid4().hex[:8],
            user_id=user_id,
            name=name,
            description=description,
            body=body,
            source_url=source_url,
        )
        self.rows[row.id] = row
        return row

    async def get(self, skill_id, user_id):
        row = self.rows.get(skill_id)
        return row if row and row.user_id == user_id else None

    async def delete(self, skill_id, user_id):
        row = self.rows.get(skill_id)
        if row is None or row.user_id != user_id:
            return False
        del self.rows[skill_id]
        return True

    async def enabled_for_conversation(self, cid):
        return [self.rows[i] for i in self.enabled.get(cid, []) if i in self.rows]

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


async def test_skill_budget_skips_whole_skills_never_truncates():
    repo = FakeSkillRepository()
    owner = uuid.uuid4()
    big = await repo.create(
        user_id=owner, name="big", description="", body="x" * (SKILL_BUDGET_CHARS - 10)
    )
    second = await repo.create(user_id=owner, name="second", description="", body="y" * 100)
    repo.enabled["c1"] = [big.id, second.id]

    included, skipped = await SkillService(repo).enabled_bodies("c1")

    assert [s.name for s in included] == ["big"]
    assert [s.name for s in skipped] == ["second"]
    assert included[0].body == "x" * (SKILL_BUDGET_CHARS - 10)


async def test_skills_within_budget_are_all_included():
    repo = FakeSkillRepository()
    owner = uuid.uuid4()
    for i in range(3):
        row = await repo.create(user_id=owner, name=f"s{i}", description="", body="z" * 100)
        repo.enabled.setdefault("c1", []).append(row.id)

    included, skipped = await SkillService(repo).enabled_bodies("c1")

    assert len(included) == 3
    assert skipped == []


def test_render_skills_is_empty_for_no_skills():
    assert render_skills([]) == ""


def test_render_skills_includes_every_body():
    rendered = render_skills([skill("a", "body-a"), skill("b", "body-b")])
    assert "body-a" in rendered and "body-b" in rendered


async def test_import_rejects_plain_http():
    with pytest.raises(ImportError_):
        await SkillService(FakeSkillRepository()).import_from_url(
            uuid.uuid4(), "http://example.com/skill.md"
        )


async def test_import_rejects_a_non_url():
    with pytest.raises(ImportError_):
        await SkillService(FakeSkillRepository()).import_from_url(
            uuid.uuid4(), "ftp://example.com/skill.md"
        )


def test_mcp_tool_names_are_namespaced():
    assert tool_name("Linear Prod", "create") == "mcp__Linear_Prod__create"
    assert tool_name("x", "bash") != "bash"


def test_mcp_tool_uses_the_remote_schema_verbatim():
    schema = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}
    tool = McpTool(
        connection="c",
        remote_name="search",
        description="Search",
        input_schema=schema,
        invoke=lambda n, a: "ok",
    )
    assert to_openai_schema(tool)["function"]["parameters"] == schema


def test_mcp_tool_tolerates_an_empty_schema():
    tool = McpTool(
        connection="c", remote_name="ping", description="", input_schema={},
        invoke=lambda n, a: "pong",
    )
    params = to_openai_schema(tool)["function"]["parameters"]
    assert params["type"] == "object"


def _import_service(handler) -> SkillService:
    return SkillService(FakeSkillRepository(), transport=httpx.MockTransport(handler))


async def test_import_snapshots_a_text_body():
    service = _import_service(
        lambda request: httpx.Response(
            200, text="# Review", headers={"content-type": "text/plain; charset=utf-8"}
        )
    )
    row = await service.import_from_url(
        uuid.uuid4(), "https://gist.example.com/review.md"
    )
    assert row.name == "review"
    assert row.body == "# Review"
    assert row.source_url == "https://gist.example.com/review.md"


async def test_import_rejects_the_wrong_content_type():
    service = _import_service(
        lambda request: httpx.Response(
            200, content=b"\x00", headers={"content-type": "application/octet-stream"}
        )
    )
    with pytest.raises(ImportError_, match="content type"):
        await service.import_from_url(uuid.uuid4(), "https://example.com/skill.md")


async def test_import_rejects_an_oversized_body():
    service = _import_service(
        lambda request: httpx.Response(
            200, content=b"x" * (256 * 1024 + 1), headers={"content-type": "text/plain"}
        )
    )
    with pytest.raises(ImportError_, match="256 KB"):
        await service.import_from_url(uuid.uuid4(), "https://example.com/skill.md")


async def test_import_rejects_a_redirect_to_http():
    def handler(request):
        if request.url.scheme == "https":
            return httpx.Response(302, headers={"location": "http://example.com/x.md"})
        return httpx.Response(200, text="body", headers={"content-type": "text/plain"})

    with pytest.raises(ImportError_, match="https"):
        await _import_service(handler).import_from_url(
            uuid.uuid4(), "https://example.com/skill.md"
        )


class _PlainAction(Action):
    value: int


class _PlainTool(Tool):
    name = "plain"
    description = "plain"
    action_type = _PlainAction
    observation_type = Action

    def execute(self, action, sandbox):
        raise NotImplementedError


def test_to_openai_schema_falls_back_to_the_pydantic_model():
    params = to_openai_schema(_PlainTool())["function"]["parameters"]
    assert params == _PlainAction.model_json_schema()


def test_mcp_tools_are_risky_under_the_confirm_policy():
    policy = ConfirmPolicy("risky")
    call = ActionEvent(
        tool_name=tool_name("linear", "create_issue"), arguments={}, tool_call_id="1"
    )
    assert policy.needs_confirmation(call)


def _host():
    events: list = []
    agent = SimpleNamespace(skills_block="", tools=ToolRegistry([_PlainTool()]))
    conversation = SimpleNamespace(agent=agent, add_event=events.append)
    host = SimpleNamespace(conversation=conversation, mcp_tools={}, mcp_skipped=set())
    return host, events


def _apply(host, targets, skills_block=""):
    ManagedConversation.apply_extensions(host, skills_block, targets)


def _specs(*names):
    return [mcp_client.McpToolSpec(name=n, description="", input_schema={}) for n in names]


def _target(name):
    return mcp_client.McpTarget(name=name, url=f"https://{name}.example.com/mcp")


@pytest.fixture
def servers(monkeypatch):
    catalog: dict[str, list | Exception] = {}

    async def discover(target):
        result = catalog[target.name]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(runtime_manager.mcp, "discover", discover)
    return catalog


def test_enabled_connections_register_namespaced_tools(servers):
    servers["linear"] = _specs("create_issue", "search")
    host, events = _host()
    _apply(host, {"c1": _target("linear")}, skills_block="## skill")

    tools = host.conversation.agent.tools
    assert "mcp__linear__create_issue" in tools and "mcp__linear__search" in tools
    assert host.conversation.agent.skills_block == "## skill"
    assert events == []


def test_an_unreachable_server_degrades_with_an_error(servers):
    servers["dead"] = mcp_client.McpError("connection refused")
    servers["live"] = _specs("ping")
    host, events = _host()
    _apply(host, {"c1": _target("dead"), "c2": _target("live")})

    assert "mcp__live__ping" in host.conversation.agent.tools
    assert len(events) == 1 and isinstance(events[0], ErrorEvent)
    assert "dead" in events[0].message
    assert host.mcp_skipped == {"c1"}


def test_the_tool_budget_skips_whole_connections(servers):
    servers["big"] = _specs(*[f"t{i}" for i in range(MAX_TOOLS - 1)])
    servers["pair"] = _specs("a", "b")
    host, events = _host()
    _apply(host, {"c1": _target("big"), "c2": _target("pair")})

    names = [t.name for t in host.conversation.agent.tools.all()]
    assert not any(n.startswith("mcp__pair__") for n in names)
    assert host.mcp_skipped == {"c2"}
    assert "budget" in events[0].message


def test_a_collision_after_namespacing_is_skipped(servers):
    servers["a b"] = _specs("x")
    servers["a_b"] = _specs("x", "y")
    host, _ = _host()
    _apply(host, {"c1": _target("a b"), "c2": _target("a_b")})

    assert host.mcp_tools == {"c1": ["mcp__a_b__x"], "c2": ["mcp__a_b__y"]}


def test_disabling_a_connection_unregisters_its_tools(servers):
    servers["linear"] = _specs("search")
    host, _ = _host()
    _apply(host, {"c1": _target("linear")})
    _apply(host, {})

    assert "mcp__linear__search" not in host.conversation.agent.tools
    assert "plain" in host.conversation.agent.tools
    assert host.mcp_tools == {}


def test_a_known_connection_is_not_rediscovered(servers):
    servers["linear"] = _specs("search")
    host, _ = _host()
    _apply(host, {"c1": _target("linear")})
    servers["linear"] = mcp_client.McpError("should not be called")
    _apply(host, {"c1": _target("linear")})

    assert host.mcp_tools == {"c1": ["mcp__linear__search"]}


class FakeService:
    def __init__(self) -> None:
        self.conversations: dict[str, SimpleNamespace] = {}

    def add(self, cid, user_id):
        self.conversations[cid] = SimpleNamespace(
            conversation=SimpleNamespace(id=cid), user_id=user_id, mcp_skipped=set()
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
        ("post", "/skills"),
        ("post", "/skills/import"),
        ("get", "/mcp/connections"),
        ("post", "/mcp/connections"),
    ],
)
async def test_extension_routes_require_authentication(client, method, path):
    kwargs = {"json": {}} if method == "post" else {}
    response = await getattr(client, method)(path, **kwargs)
    assert response.status_code == 401


async def test_skills_are_scoped_to_their_owner(client):
    created = await client.post(
        "/skills",
        json={"name": "mine", "description": "", "body": "hello"},
        headers=bearer("token-a"),
    )
    assert created.status_code == 200

    assert [s["name"] for s in (await client.get("/skills", headers=bearer("token-a"))).json()] == ["mine"]
    assert (await client.get("/skills", headers=bearer("token-b"))).json() == []

    foreign = await client.delete(
        f"/skills/{created.json()['id']}", headers=bearer("token-b")
    )
    assert foreign.status_code == 404


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
    created = (
        await client.post(
            "/skills",
            json={"name": "review", "body": "be thorough"},
            headers=bearer("token-a"),
        )
    ).json()

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
    for name, size in (("small", 10), ("huge", SKILL_BUDGET_CHARS)):
        row = (
            await client.post(
                "/skills", json={"name": name, "body": "x" * size}, headers=bearer("token-a")
            )
        ).json()
        await client.put(
            f"/conversations/conv-a/skills/{row['id']}",
            json={"enabled": True},
            headers=bearer("token-a"),
        )
    listed = (await client.get("/conversations/conv-a/skills", headers=bearer("token-a"))).json()
    assert {i["name"]: i["skipped"] for i in listed} == {"small": False, "huge": True}


async def test_a_foreign_conversation_or_extension_is_404(client, user_a, user_b):
    service = client._transport.app.state.service
    service.add("conv-a", uuid.UUID(user_a.sub))
    service.add("conv-b", uuid.UUID(user_b.sub))
    skill_b = (
        await client.post("/skills", json={"name": "b", "body": "b"}, headers=bearer("token-b"))
    ).json()
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
    from miniagent.agent import Agent

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
    agent = Agent(llm=SimpleNamespace(model="m"), tools=tools, policy=object(), task_router=object())
    policy = ConfirmPolicy("risky")
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
    assert not agent._blocked_in_plan_mode(_call("search"))
    assert agent._blocked_in_plan_mode(_call("create_issue"))


def test_discovery_reads_the_read_only_hint(servers):
    servers["linear"] = [
        mcp_client.McpToolSpec(name="search", description="", input_schema={}, read_only=True),
        mcp_client.McpToolSpec(name="create", description="", input_schema={}),
    ]
    host, _ = _host()
    _apply(host, {"c1": _target("linear")})
    tools = host.conversation.agent.tools
    assert tools["mcp__linear__search"].read_only
    assert not tools["mcp__linear__create"].read_only
