from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from backend.api.conversations import router
from backend.repository import ConversationRepository, UserRepository
from backend.runtime.manager import ConversationManager
from backend.service import ConversationService
from miniagent.agent import Agent
from miniagent.config import Settings
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation, Status
from miniagent.events import ObservationEvent
from miniagent.llm import LLMResponse, ToolCall
from miniagent.policy import CommandPolicy
from miniagent.sandbox.local import LocalSandbox
from miniagent.tools.base import ToolRegistry
from miniagent.tools.bash import BashTool
from miniagent.tools.file_edit import FileEditTool
from miniagent.tools.finish import FinishTool
from tests.fakes import FakeConnectionRepository
from tests.test_agent_history import QueueLLM
from tests.test_auth_api import bearer
from tests.test_docker_isolation import docker_only
from tests.test_repository_ownership import sessionmaker  # noqa: F401

AUTH = bearer("token-a")

_RISK = {
    "ls": CommandPolicy(risk="safe", read_only=True),
    "rm -rf build": CommandPolicy(risk="dangerous"),
}


class TablePolicy:
    def classify_bash(self, command: str) -> CommandPolicy:
        return _RISK[command]

    def classify_finish_message(self, message: str) -> CommandPolicy:
        return CommandPolicy(risk="safe", read_only=True)


class ScriptLLM(QueueLLM):
    def complete(self, messages, tools=None, phase="agent"):
        step = super().complete(messages, tools, phase)
        return step() if callable(step) else step


def _call(name: str, **arguments) -> LLMResponse:
    return LLMResponse(
        tool_calls=[ToolCall(id=f"call_{uuid.uuid4().hex[:6]}", name=name, arguments=arguments)]
    )


def _edit(path: str) -> LLMResponse:
    return _call("file_edit", command="create", path=path, content="x\n")


def _conversation(tmp_path, mode, *steps) -> Conversation:
    agent = Agent(
        llm=ScriptLLM(*steps),
        tools=ToolRegistry([BashTool(), FileEditTool(), FinishTool()]),
        policy=TablePolicy(),
    )
    return Conversation(
        agent=agent,
        sandbox=LocalSandbox(str(tmp_path)),
        confirm_policy=ConfirmPolicy(mode),
        stuck_detection=False,
    )


def test_ask_pauses_a_workspace_edit_but_not_a_read_or_finish(tmp_path):
    conversation = _conversation(
        tmp_path, "ask", _call("bash", command="ls"), _edit("notes.md"), _call("finish", message="Done.")
    )
    conversation.send_message("write notes")
    conversation.run()

    assert conversation.status == Status.WAITING_FOR_CONFIRMATION
    assert conversation.pending_action().tool_name == "file_edit"
    assert any(
        isinstance(e, ObservationEvent) and e.tool_name == "bash" and not e.error
        for e in conversation.events
    )

    conversation.approve(conversation.pending_action().tool_call_id)
    assert conversation.status == Status.FINISHED
    assert (tmp_path / "notes.md").exists()


def test_auto_runs_workspace_edits_and_pauses_on_danger_or_outside_paths(tmp_path):
    (tmp_path / "build").mkdir()
    conversation = _conversation(
        tmp_path,
        "auto",
        _edit("notes.md"),
        _call("bash", command="rm -rf build"),
        _call("file_edit", command="view", path="/etc/hosts"),
    )
    conversation.send_message("tidy up")
    conversation.run()

    assert (tmp_path / "notes.md").exists()
    assert conversation.pending_action().arguments == {"command": "rm -rf build"}

    conversation.reject(conversation.pending_action().tool_call_id)
    assert conversation.status == Status.WAITING_FOR_CONFIRMATION
    assert conversation.pending_action().arguments["path"] == "/etc/hosts"
    assert (tmp_path / "build").is_dir()


@pytest.fixture
async def stack(tmp_path, sessionmaker, user_a, verifier):  # noqa: F811
    users = UserRepository(sessionmaker)
    await users.upsert(user_id=uuid.UUID(user_a.sub), email=user_a.email, avatar_url=None)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    settings = Settings(
        _env_file=None,
        openai_api_key="unused",
        sandbox_provider="local",
        workspace_dir=str(workspace),
    )
    manager = ConversationManager(settings, data_dir=tmp_path / "data")
    service = ConversationService(
        manager, ConversationRepository(sessionmaker), FakeConnectionRepository()
    )
    app = FastAPI()
    app.include_router(router)
    app.state.verifier = verifier
    app.state.users = users
    app.state.connections = FakeConnectionRepository()
    app.state.service = service
    app.state.settings = settings
    app.state.skills = None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield SimpleNamespace(
            client=client, service=service, manager=manager, workspace=workspace
        )


async def _settle(service: ConversationService) -> None:
    while service._tasks:
        await asyncio.gather(*list(service._tasks))


async def _start(stack, llm: ScriptLLM, **body) -> str:
    resp = await stack.client.post("/conversations", json=body, headers=AUTH)
    assert resp.status_code == 200, resp.text
    cid = resp.json()["id"]
    agent = stack.manager.get(cid).conversation.agent
    agent.llm, agent.policy = llm, TablePolicy()
    await _settle(stack.service)
    return cid


async def _send(stack, cid: str, text: str, **body) -> None:
    resp = await stack.client.post(
        f"/conversations/{cid}/messages", json={"text": text, **body}, headers=AUTH
    )
    assert resp.status_code == 200, resp.text
    await _settle(stack.service)


async def _info(stack, cid: str) -> dict:
    return (await stack.client.get(f"/conversations/{cid}", headers=AUTH)).json()


def _mid_run(request, then: LLMResponse):
    loop = asyncio.get_running_loop()

    def step() -> LLMResponse:
        resp = asyncio.run_coroutine_threadsafe(request(), loop).result(10)
        assert resp.status_code == 200, resp.text
        return then

    return step


async def test_plan_mode_rejects_writes_until_the_plan_is_approved(stack):
    plan = _call("present_plan", title="Add notes", steps=[{"title": "Write notes.md"}])
    llm = ScriptLLM(
        _edit("notes.md"),
        plan,
        _call("update_plan", step=9, status="done"),
        _edit("notes.md"),
        _call("update_plan", step=1, status="done"),
        _call("finish", message="Wrote it."),
    )
    cid = await _start(stack, llm)

    await _send(stack, cid, "add notes", plan_mode=True)
    info = await _info(stack, cid)
    assert (info["status"], info["plan_mode"], info["plan"]["title"]) == ("idle", True, "Add notes")
    assert not (stack.workspace / "notes.md").exists()

    resp = await stack.client.post(f"/conversations/{cid}/plan/approve", headers=AUTH)
    assert resp.status_code == 200, resp.text
    await _settle(stack.service)
    info = await _info(stack, cid)
    assert (info["status"], info["plan_mode"]) == ("finished", False)
    assert info["plan"]["steps"][0]["status"] == "done"
    assert (stack.workspace / "notes.md").exists()
    bad_step = next(
        e
        for e in stack.manager.get(cid).conversation.events
        if getattr(e, "tool_name", None) == "update_plan" and e.kind == "observation"
    )
    assert bad_step.error


async def test_full_access_is_refused_outside_a_container(stack):
    resp = await stack.client.post(
        "/conversations", json={"sandbox_provider": "local", "permission_mode": "full"}, headers=AUTH
    )
    assert resp.status_code == 422
    cid = await _start(stack, ScriptLLM())
    patch = await stack.client.patch(
        f"/conversations/{cid}", json={"permission_mode": "full"}, headers=AUTH
    )
    send = await stack.client.post(
        f"/conversations/{cid}/messages", json={"text": "go", "permission_mode": "full"}, headers=AUTH
    )
    assert (patch.status_code, send.status_code) == (422, 422)
    assert (await _info(stack, cid))["permission_mode"] == "auto"


@docker_only
async def test_full_access_runs_a_dangerous_command_in_docker(stack):
    llm = ScriptLLM(_call("bash", command="rm -rf build"), LLMResponse(text="Removed build."))
    cid = await _start(stack, llm, sandbox_provider="docker", permission_mode="full")
    sandbox = stack.manager.get(cid).sandbox
    try:
        await asyncio.to_thread(sandbox.write_file, "build/out.txt", "artifact\n")
        await _send(stack, cid, "delete build", permission_mode="full")
        assert (await _info(stack, cid))["status"] == "idle"
        assert (await asyncio.to_thread(sandbox.run_command, "test -e build")).exit_code != 0
    finally:
        await asyncio.to_thread(sandbox.close)
        await asyncio.to_thread(stack.manager.release_workspace, cid, None)


async def test_a_mode_change_during_a_run_applies_to_the_next_action(stack):
    def patch():
        return stack.client.patch(
            f"/conversations/{cid}", json={"permission_mode": "ask"}, headers=AUTH
        )

    llm = ScriptLLM(_edit("first.md"), _mid_run(patch, _edit("second.md")))
    cid = await _start(stack, llm)
    await _send(stack, cid, "write two files")

    assert (await _info(stack, cid))["status"] == "waiting_for_confirmation"
    assert (stack.workspace / "first.md").exists()
    assert not (stack.workspace / "second.md").exists()


async def test_a_message_without_a_permission_mode_keeps_the_current_one(stack):
    cid = await _start(stack, ScriptLLM(LLMResponse(text="Done.")))
    await stack.client.patch(
        f"/conversations/{cid}", json={"permission_mode": "ask"}, headers=AUTH
    )

    await _send(stack, cid, "hello")

    assert (await _info(stack, cid))["permission_mode"] == "ask"


async def test_a_steered_message_switches_plan_mode_mid_run(stack):
    def steer():
        return stack.client.post(
            f"/conversations/{cid}/messages",
            json={"text": "plan it first", "plan_mode": True},
            headers=AUTH,
        )

    llm = ScriptLLM(_mid_run(steer, _edit("steered.md")), LLMResponse(text="Planning."))
    cid = await _start(stack, llm)
    await _send(stack, cid, "go")

    assert (await _info(stack, cid))["plan_mode"] is True
    assert not (stack.workspace / "steered.md").exists()


async def test_a_queued_message_brings_its_plan_mode_when_it_runs(stack):
    def queue():
        return stack.client.post(
            f"/conversations/{cid}/messages",
            json={"text": "then plan the rest", "plan_mode": True, "mode": "queue"},
            headers=AUTH,
        )

    llm = ScriptLLM(
        _mid_run(queue, _edit("now.md")),
        LLMResponse(text="Done."),
        _edit("later.md"),
        LLMResponse(text="Planning."),
    )
    cid = await _start(stack, llm)
    await _send(stack, cid, "go")

    assert (stack.workspace / "now.md").exists()
    assert not (stack.workspace / "later.md").exists()
    assert (await _info(stack, cid))["plan_mode"] is True


async def test_a_revived_conversation_keeps_its_modes(stack):
    cid = await _start(stack, ScriptLLM(), permission_mode="ask")
    resp = await stack.client.patch(f"/conversations/{cid}", json={"plan_mode": True}, headers=AUTH)
    assert resp.status_code == 200, resp.text
    stack.manager.remove(cid)

    info = await _info(stack, cid)
    assert stack.manager.get(cid) is not None
    assert (info["permission_mode"], info["plan_mode"]) == ("ask", True)
