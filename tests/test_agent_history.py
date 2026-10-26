from __future__ import annotations

import pytest

from miniagent.agent import Agent
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation, Status
from miniagent.events import (
    ActionEvent,
    ErrorEvent,
    MessageEvent,
    ObservationEvent,
    WorkerEvent,
)
from miniagent.llm import LLMResponse, ToolCall
from miniagent.policy import CommandPolicy
from miniagent.sandbox.base import CommandResult, Sandbox
from miniagent.sandbox.local import LocalSandbox
from miniagent.tools.base import ToolRegistry
from miniagent.tools.finish import FinishTool
from miniagent.tools.terminal import TerminalTool
from tests.test_sandbox_failures import SafePolicy


class QueueLLM:
    model = "scripted"

    def __init__(self, *responses: LLMResponse) -> None:
        self.responses = list(responses)
        self.seen: list[list[dict]] = []

    def context_window(self) -> int:
        return 1_000_000

    def count_tokens(self, messages, tools=None) -> int:
        return 0

    def complete(self, messages, tools=None, phase="agent", tool_choice="auto"):
        if phase == "finish_nudge":
            return LLMResponse()
        self.seen.append(messages)
        return self.responses.pop(0)


class EchoSandbox(Sandbox):
    provider = "echo"

    def __init__(self) -> None:
        self.workspace_dir = "/w"
        self.commands: list[str] = []

    def run_command(self, command, timeout=30, env=None):
        self.commands.append(command)
        return CommandResult(stdout="ok", stderr="", exit_code=0)

    def write_file(self, path, content): ...
    def read_file(self, path): raise FileNotFoundError(path)
    def list_files(self, path): return []
    def close(self): ...


class MutatingPolicy(SafePolicy):
    def classify_bash(self, command: str) -> CommandPolicy:
        return CommandPolicy(risk="mutating", read_only=False)


def _conversation(
    llm, confirm="full", sandbox: Sandbox | None = None, policy=SafePolicy()
) -> tuple[Conversation, Sandbox]:
    agent = Agent(
        llm=llm,
        tools=ToolRegistry([TerminalTool(), FinishTool()]),
        policy=policy,
    )
    sandbox = sandbox if sandbox is not None else EchoSandbox()
    conversation = Conversation(
        agent=agent,
        sandbox=sandbox,
        confirm_policy=ConfirmPolicy(confirm),
        stuck_detection=False,
    )
    return conversation, sandbox


@pytest.fixture
def workspace_conversation(tmp_path):
    built: list[Conversation] = []

    def build(llm, confirm="full", policy=SafePolicy()) -> Conversation:
        conversation, _ = _conversation(llm, confirm, LocalSandbox(str(tmp_path)), policy)
        built.append(conversation)
        return conversation

    yield build
    for conversation in built:
        conversation.agent.close()


def _terminal(call_id: str, command: str) -> LLMResponse:
    return LLMResponse(
        tool_calls=[ToolCall(id=call_id, name="terminal", arguments={"command": command})]
    )


def test_a_new_message_closes_a_call_awaiting_approval_without_running_it(
    tmp_path, workspace_conversation
):
    llm = QueueLLM(_terminal("c1", "touch cleaned"), LLMResponse(text="ok, skipped"))
    conversation = workspace_conversation(llm, confirm="ask", policy=MutatingPolicy())
    conversation.send_message("clean the build")
    conversation.run()
    assert conversation.status == Status.WAITING_FOR_CONFIRMATION

    conversation.send_message("actually, don't")
    conversation.run()

    assert not (tmp_path / "cleaned").exists()
    closing = [e for e in conversation.events if isinstance(e, ObservationEvent)]
    assert closing[0].tool_call_id == "c1" and closing[0].error
    second = llm.seen[-1]
    tool_index = next(i for i, m in enumerate(second) if m.get("role") == "tool")
    assert second[tool_index - 1]["tool_calls"][0]["id"] == "c1"
    assert second[tool_index + 1]["role"] == "user"


def test_an_orphan_from_an_earlier_run_is_closed_not_executed(
    tmp_path, workspace_conversation
):
    llm = QueueLLM(LLMResponse(text="fine"))
    conversation = workspace_conversation(llm)
    conversation.add_event(MessageEvent(role="user", text="go"))
    conversation.add_event(
        ActionEvent(tool_name="terminal", arguments={"command": "touch deployed"}, tool_call_id="c9")
    )
    conversation.run()
    assert not (tmp_path / "deployed").exists()
    assert any(
        isinstance(e, ObservationEvent) and e.tool_call_id == "c9" and e.error
        for e in conversation.events
    )


def test_approval_still_runs_the_pending_call(tmp_path, workspace_conversation):
    llm = QueueLLM(_terminal("c1", "touch tested"), LLMResponse(text="passed"))
    conversation = workspace_conversation(llm, confirm="ask", policy=MutatingPolicy())
    conversation.send_message("run tests")
    conversation.run()
    conversation.approve("c1")
    assert (tmp_path / "tested").exists()


def test_a_stale_approval_does_not_approve_the_next_pending_call(
    tmp_path, workspace_conversation
):
    llm = QueueLLM(
        _terminal("c1", "touch tested"), _terminal("c2", "touch deployed"), LLMResponse(text="done")
    )
    conversation = workspace_conversation(llm, confirm="ask", policy=MutatingPolicy())
    conversation.send_message("test then deploy")
    conversation.run()
    conversation.approve("c1")
    assert conversation.awaits("c2")

    conversation.approve("c1")
    conversation.reject("c1")

    assert not (tmp_path / "deployed").exists()
    assert conversation.awaits("c2")


def test_a_call_interrupted_by_a_restart_keeps_its_result_next_to_it(workspace_conversation):
    llm = QueueLLM(LLMResponse(text="picking up again"))
    conversation = workspace_conversation(llm)
    conversation.add_event(MessageEvent(role="user", text="review the branch"))
    conversation.add_event(
        ActionEvent(tool_name="terminal", arguments={"command": "git diff"}, tool_call_id="c1")
    )
    conversation.add_event(ErrorEvent(message="The server restarted while this run was in progress."))
    conversation.send_message("??")
    conversation.run()

    sent = llm.seen[-1]
    call = next(i for i, m in enumerate(sent) if m.get("tool_calls"))
    assert sent[call + 1] == {**sent[call + 1], "role": "tool", "tool_call_id": "c1"}
    assert [m["role"] for m in sent].count("tool") == 1
    assert sent[call + 2]["content"].startswith("[error]")


def test_worker_relays_do_not_split_one_turns_parallel_calls(workspace_conversation):
    llm = QueueLLM(LLMResponse(text="done"))
    conversation = workspace_conversation(llm)
    conversation.add_event(MessageEvent(role="user", text="look around"))
    for call_id in ("c1", "c2"):
        conversation.add_event(
            ActionEvent(tool_name="terminal", arguments={"command": "ls"}, tool_call_id=call_id)
        )
        conversation.add_event(
            WorkerEvent(
                parent_tool_call_id="t1",
                worker_id="w1",
                event=MessageEvent(role="assistant", text="worker step"),
            )
        )
    for call_id in ("c1", "c2"):
        conversation.add_event(
            ObservationEvent(tool_name="terminal", tool_call_id=call_id, content="ok")
        )
    conversation.run()

    sent = llm.seen[-1]
    turns = [m for m in sent if m.get("tool_calls")]
    assert len(turns) == 1
    assert [c["id"] for c in turns[0]["tool_calls"]] == ["c1", "c2"]


def test_a_long_user_message_reaches_the_model_whole(workspace_conversation):
    llm = QueueLLM(LLMResponse(text="read it"))
    conversation = workspace_conversation(llm)
    spec = "requirement line\n" * 2_000
    conversation.send_message(spec)
    conversation.run()

    assert any(m.get("content") == spec for m in llm.seen[-1])


def test_a_steering_message_gets_a_fresh_step_budget(tmp_path):
    from tests.test_queue_steer import SteeringProbe

    llm = QueueLLM(
        LLMResponse(tool_calls=[ToolCall(id="p1", name="probe", arguments={})]),
        _terminal("t1", "ls"),
        LLMResponse(text="README updated"),
    )
    conversation = Conversation(
        agent=Agent(llm=llm, tools=ToolRegistry([SteeringProbe(), TerminalTool(), FinishTool()]), policy=SafePolicy()),
        sandbox=LocalSandbox(str(tmp_path)),
        confirm_policy=ConfirmPolicy("full"),
        stuck_detection=False,
        max_iterations=2,
    )
    conversation.send_message("fix the bug")
    try:
        conversation.run()
    finally:
        conversation.agent.close()

    assert not conversation.hit_step_limit
    assert conversation.events[-1].text == "README updated"


def test_one_empty_reply_is_retried_before_it_counts_as_an_error(workspace_conversation):
    llm = QueueLLM(LLMResponse(), LLMResponse(text="here it is"))
    conversation = workspace_conversation(llm)
    conversation.send_message("answer")
    conversation.run()

    assert conversation.status == Status.IDLE
    assert conversation.events[-1].text == "here it is"
