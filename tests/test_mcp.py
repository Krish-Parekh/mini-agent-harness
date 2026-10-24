from __future__ import annotations

import shutil
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest
import uvicorn
from fastmcp.mcp_config import RemoteMCPServer, StdioMCPServer

from backend.repository import McpConnectionRepository
from backend.runtime import mcp
from backend.runtime.manager import ConversationManager
from backend.service.extension import McpService
from miniagent.config import Settings
from miniagent.events import ActionEvent, ErrorEvent
from miniagent.tools.mcp import McpAction
from tests.mcp_server import server as tracker_server
from tests.test_repository_ownership import _make_conversation, repos, sessionmaker  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
TRACKER = StdioMCPServer(command=sys.executable, args=[str(ROOT / "tests" / "mcp_server.py")])
API_KEY = "tracker-secret"


def _tracker(**extra) -> mcp.McpTarget:
    return mcp.McpTarget(name="tracker", server=TRACKER.model_copy(update=extra))


@pytest.fixture(scope="module")
def http_tracker():
    app = tracker_server.streamable_http_app()

    async def guarded(scope, receive, send):
        headers = dict(scope.get("headers") or [])
        if scope["type"] == "http" and headers.get(b"x-api-key") != API_KEY.encode():
            await send({"type": "http.response.start", "status": 401, "headers": []})
            await send({"type": "http.response.body", "body": b"unauthorized"})
            return
        await app(scope, receive, send)

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    http = uvicorn.Server(uvicorn.Config(guarded, port=port, log_level="error"))
    thread = threading.Thread(target=http.run, daemon=True)
    thread.start()
    while not http.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    http.should_exit = True
    thread.join()


async def test_open_lists_tools_with_their_read_only_hints_and_instructions():
    session = mcp.McpSession(_tracker())
    info = await session.open()
    await session.close()

    hints = {tool.name: tool.read_only for tool in info.tools}
    assert hints == {"search": True, "create_issue": False, "pid": True, "fail": False}
    assert info.instructions == "Search before you create an issue."


async def test_one_server_process_serves_every_call_in_a_session():
    session = mcp.McpSession(_tracker())
    await session.open()
    first = await session.call("pid", {})
    second = await session.call("pid", {})
    await session.close()

    assert first == second


async def test_a_tool_error_becomes_an_mcp_error():
    session = mcp.McpSession(_tracker())
    await session.open()
    with pytest.raises(mcp.McpError, match="tracker is down"):
        await session.call("fail", {})
    await session.close()


async def test_trusted_tools_from_the_config_count_as_read_only():
    info = await mcp.discover(_tracker(trustedTools=["create_issue"]))

    assert {tool.name for tool in info.tools if tool.read_only} == {
        "search",
        "pid",
        "create_issue",
    }


async def test_http_servers_receive_the_auth_header(http_tracker):
    target = mcp.McpTarget(
        name="tracker",
        server=RemoteMCPServer(
            url=http_tracker, headers={"x-api-key": API_KEY}, transport="http"
        ),
    )
    session = mcp.McpSession(target)
    await session.open()
    text = await session.call("search", {"query": "login"})
    await session.close()

    assert text == "found 2 issues for login"


def test_config_servers_run_inside_the_conversation_workspace(tmp_path):
    config = mcp.load_config(ROOT / "mcp.json")
    targets = mcp.config_targets(config, tmp_path)

    shadcn = targets["config:shadcn"]
    assert shadcn.server.cwd == str(tmp_path / ".")
    assert "search_items_in_registries" in shadcn.trusted_tools


def _conversation(tmp_path):
    settings = Settings(_env_file=None, sandbox_provider="local")
    manager = ConversationManager(settings, data_dir=tmp_path / "data")
    return manager.create(
        user_id=uuid.uuid4(), provider="local", workspace_dir=str(tmp_path / "ws")
    )


async def test_a_conversation_registers_runs_and_drops_server_tools(tmp_path):
    managed = _conversation(tmp_path)
    tools = managed.conversation.agent.tools

    managed.apply_extensions("", {}, {"c1": _tracker()})

    assert {"mcp__tracker__search", "mcp__tracker__create_issue"} <= set(
        t.name for t in tools.all()
    )
    assert managed.conversation.agent.mcp_instructions == {
        "tracker": "Search before you create an issue."
    }
    search = tools["mcp__tracker__search"]
    assert search.execute(McpAction(query="crash"), managed.sandbox).content == (
        "found 2 issues for crash"
    )
    call = ActionEvent(tool_name="mcp__tracker__search", arguments={}, tool_call_id="1")
    assert not managed.conversation.agent._needs_confirmation(call, managed.conversation)
    create = ActionEvent(
        tool_name="mcp__tracker__create_issue", arguments={}, tool_call_id="2"
    )
    assert managed.conversation.agent._needs_confirmation(create, managed.conversation)

    managed.apply_extensions("", {}, {})

    assert "mcp__tracker__search" not in tools
    assert managed.mcp_sessions == {}
    assert managed.conversation.agent.mcp_instructions == {}


async def test_closing_a_conversation_closes_its_sessions(tmp_path):
    managed = _conversation(tmp_path)
    managed.apply_extensions("", {}, {"c1": _tracker()})
    session = managed.mcp_sessions["c1"]

    managed.close_mcp()

    assert "mcp__tracker__search" not in managed.conversation.agent.tools
    with pytest.raises(mcp.McpError):
        mcp.bridge.run(session.call("search", {"query": "x"}))


async def test_an_unstartable_server_degrades_to_an_error_event(tmp_path):
    managed = _conversation(tmp_path)
    ghost = mcp.McpTarget(
        name="ghost", server=StdioMCPServer(command="no-such-mcp-server", args=[])
    )

    managed.apply_extensions("", {}, {"c1": ghost, "c2": _tracker()})

    errors = [e for e in managed.conversation.events if isinstance(e, ErrorEvent)]
    assert len(errors) == 1 and "ghost" in errors[0].message
    assert managed.mcp_skipped == {"c1"}
    assert "mcp__tracker__search" in managed.conversation.agent.tools
    managed.close_mcp()


async def test_a_conversation_gets_its_enabled_connections_and_the_config_servers(
    repos, sessionmaker, http_tracker, tmp_path  # noqa: F811
):
    conversations, _, owner, _ = repos
    await _make_conversation(conversations, "c1", owner)
    connections = McpConnectionRepository(sessionmaker)
    row = await connections.create(
        user_id=owner,
        name="tracker",
        url=http_tracker,
        auth_header="x-api-key",
        auth_value=API_KEY,
    )
    await connections.set_enabled("c1", row.id, True)
    service = McpService(connections, mcp.load_config(ROOT / "mcp.json"))

    targets = await service.targets("c1", tmp_path)
    remote_only = await service.targets("c1", None)

    assert set(targets) == {row.id, "config:shadcn"}
    assert set(remote_only) == {row.id}
    session = mcp.McpSession(targets[row.id])
    await session.open()
    assert await session.call("search", {"query": "db"}) == "found 2 issues for db"
    await session.close()


shadcn_only = pytest.mark.skipif(shutil.which("npx") is None, reason="needs npx")


@shadcn_only
async def test_the_shipped_shadcn_server_searches_its_registry(tmp_path):
    target = mcp.config_targets(mcp.load_config(ROOT / "mcp.json"), tmp_path)[
        "config:shadcn"
    ]
    session = mcp.McpSession(target)
    info = await session.open()
    text = await session.call(
        "search_items_in_registries", {"registries": ["@shadcn"], "query": "button"}
    )
    await session.close()

    assert all(tool.read_only for tool in info.tools)
    assert "button (registry:ui)" in text
