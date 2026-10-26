from __future__ import annotations

from miniagent.agent import SKETCH_COMMAND, Agent
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation, Status
from miniagent.events import ErrorEvent, ObservationEvent
from miniagent.llm import LLMResponse, ToolCall
from miniagent.policy import CommandPolicy
from miniagent.sandbox.base import CommandResult, Sandbox, SandboxError, SandboxExpired
from miniagent.tools.base import ToolRegistry
from miniagent.tools.finish import FinishTool
from miniagent.tools.terminal import TerminalTool


class ScriptedLLM:
    model = "scripted"

    def __init__(self) -> None:
        self.calls = 0

    def context_window(self) -> int:
        return 1_000_000

    def count_tokens(self, messages, tools=None) -> int:
        return 0

    def complete(self, messages, tools=None, phase="agent", tool_choice="auto"):
        self.calls += 1
        return LLMResponse(
            tool_calls=[ToolCall(id=f"c{self.calls}", name="terminal", arguments={"command": "echo hi"})]
        )


class SafePolicy:
    def classify_bash(self, command: str) -> CommandPolicy:
        return CommandPolicy(risk="safe", read_only=True, is_verification=False)

    def classify_finish_message(self, message: str) -> CommandPolicy:
        return CommandPolicy(risk="safe", read_only=True)


class FailingSandbox(Sandbox):
    """Fine for the workspace sketch, then fails on the agent's own command."""

    provider = "failing"

    def __init__(self, error: SandboxError) -> None:
        self.workspace_dir = "/w"
        self.error = error

    def run_command(self, command, timeout=30, env=None):
        if command != SKETCH_COMMAND:
            raise self.error
        return CommandResult(stdout="", stderr="", exit_code=1)

    def write_file(self, path, content): ...
    def read_file(self, path): raise FileNotFoundError(path)
    def list_files(self, path): return []
    def close(self): ...


def _run(error: SandboxError) -> tuple[Conversation, ScriptedLLM]:
    llm = ScriptedLLM()
    agent = Agent(
        llm=llm,
        tools=ToolRegistry([TerminalTool(), FinishTool()]),
        policy=SafePolicy(),
    )
    conversation = Conversation(
        agent=agent,
        sandbox=FailingSandbox(error),
        confirm_policy=ConfirmPolicy("full"),
        stuck_detection=False,
    )
    conversation.send_message("say hi")
    conversation.run()
    return conversation, llm


def test_expired_sandbox_ends_the_turn_instead_of_reaching_the_model() -> None:
    conversation, llm = _run(SandboxExpired("e2b sandbox sbx_1 is gone"))
    assert conversation.status == Status.ERROR
    assert llm.calls == 1
    errors = [e for e in conversation.events if isinstance(e, ErrorEvent)]
    assert errors[-1].message.startswith("sandbox_expired:")
    observations = [e for e in conversation.events if isinstance(e, ObservationEvent)]
    assert len(observations) == 1
    assert observations[0].error
    assert observations[0].content.startswith("Not executed: sandbox_expired.")


def test_unreachable_sandbox_is_reported_as_unavailable() -> None:
    conversation, _ = _run(SandboxError("space command stream failed"))
    errors = [e for e in conversation.events if isinstance(e, ErrorEvent)]
    assert errors[-1].message.startswith("sandbox_unavailable:")
