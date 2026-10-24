from __future__ import annotations

from pathlib import Path

from miniagent.agent import SKETCH_COMMAND, Agent
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation
from miniagent.events import CondensationEvent, ObservationEvent
from miniagent.llm import LLMResponse, ToolCall
from miniagent.sandbox.base import CommandResult, Sandbox
from miniagent.tools.base import ToolRegistry
from miniagent.tools.finish import FinishTool
from miniagent.tools.terminal import TerminalAction, TerminalObservation, TerminalTool
from tests.test_sandbox_failures import SafePolicy

SNAPSHOT_PATH = Path(__file__).parent / "fixtures" / "context.expected.md"

TEST_OUTPUT = (
    "".join(f"tests/test_app.py::test_case_{i:03d} PASSED\n" for i in range(150))
    + "tests/test_app.py::test_totals FAILED\n"
    + "E   AssertionError: assert 41 == 42\n"
    + "1 failed, 150 passed in 0.84s"
)


class SnapshotSandbox(Sandbox):
    provider = "snapshot"

    def __init__(self) -> None:
        self.workspace_dir = "/workspace/app"

    def run_command(self, command, timeout=30, env=None):
        if command == SKETCH_COMMAND:
            return CommandResult(stdout="AGENTS.md\nsrc/app.py\ntests/test_app.py\n", stderr="", exit_code=0)
        return CommandResult(stdout="", stderr="", exit_code=0)

    def write_file(self, path, content): ...

    def read_file(self, path):
        if path == "AGENTS.md":
            return "Use uv for every Python command. Never call pip directly."
        raise FileNotFoundError(path)

    def list_files(self, path): return []

    def close(self): ...


class ScriptedTerminal(TerminalTool):
    def execute(
        self,
        action: TerminalAction,
        sandbox: Sandbox,
        *,
        conversation: Conversation,
        tool_call_id: str | None = None,
    ) -> TerminalObservation:
        return TerminalObservation(
            command=action.command,
            output=TEST_OUTPUT,
            exit_code=1,
            working_dir=sandbox.workspace_dir,
            suffix="\n[The command completed with exit code 1.]",
        )


class ScriptedLLM:
    model = "scripted"

    def __init__(self) -> None:
        self.responses: list[LLMResponse] = []
        self.seen: list[list[dict]] = []

    def context_window(self) -> int:
        return 1_000_000

    def count_tokens(self, messages, tools=None) -> int:
        return 0

    def complete(self, messages, tools=None, phase="agent"):
        if phase == "finish_nudge":
            return LLMResponse()
        self.seen.append(messages)
        return self.responses.pop(0)


def _turn(conversation: Conversation, llm: ScriptedLLM, text: str, *responses: LLMResponse) -> list[dict]:
    llm.responses.extend(responses)
    conversation.send_message(text)
    conversation.run()
    return llm.seen[-1]


def capture() -> dict[str, list[dict]]:
    llm = ScriptedLLM()
    agent = Agent(
        llm=llm,
        tools=ToolRegistry([ScriptedTerminal(), FinishTool()]),
        repo="acme/app",
        branch="main",
        policy=SafePolicy(),
    )
    agent.skills_block = "- `tidy-imports`: sort and dedupe Python imports"
    conversation = Conversation(
        agent=agent,
        sandbox=SnapshotSandbox(),
        confirm_policy=ConfirmPolicy("never"),
        stuck_detection=False,
    )

    fresh = _turn(
        conversation,
        llm,
        "Why is test_totals failing?",
        LLMResponse(tool_calls=[ToolCall(id="call_1", name="terminal", arguments={"command": "uv run pytest -q"})]),
        LLMResponse(text="test_totals expects 42 but the sum is 41."),
    )

    [observation] = [e for e in conversation.events if isinstance(e, ObservationEvent)]
    conversation.add_event(
        CondensationEvent(
            summary="",
            replaced_event_ids=[],
            elided_event_ids=[observation.id],
            trigger="threshold",
            pruned_only=True,
        )
    )
    pruned = _turn(conversation, llm, "Show me the sum again.", LLMResponse(text="It is 41."))

    conversation.add_event(
        CondensationEvent(
            summary="## Primary request\nFix test_totals in acme/app.\n\n## Current state\nThe sum is 41; the test expects 42.",
            replaced_event_ids=[e.id for e in conversation.condensation_candidates()],
            trigger="threshold",
        )
    )
    summarized = _turn(conversation, llm, "Fix it.", LLMResponse(text="Fixed."))

    return {"fresh": fresh, "pruned": pruned, "summarized": summarized}


def _render_message(index: int, message: dict) -> list[str]:
    heading = f"### {index} {message['role']}"
    if message.get("tool_call_id"):
        heading += f" ({message['tool_call_id']})"
    lines = [heading, ""]
    if message.get("content"):
        lines += ["````text", message["content"], "````", ""]
    for call in message.get("tool_calls") or []:
        function = call["function"]
        lines.append(f"- tool call `{function['name']}` ({call['id']}): `{function['arguments']}`")
    if message.get("tool_calls"):
        lines.append("")
    return lines


def render() -> str:
    lines = [
        "# Context snapshot",
        "",
        "Generated by `uv run python -m tests.context_snapshot`. The exact messages MiniAgent "
        "sends to the model at three points of one scripted conversation: fresh, after old "
        "tool output is pruned, and after older history is summarized.",
    ]
    for state, messages in capture().items():
        lines += ["", f"## {state}", ""]
        for index, message in enumerate(messages):
            lines += _render_message(index, message)
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    SNAPSHOT_PATH.parent.mkdir(exist_ok=True)
    SNAPSHOT_PATH.write_text(render())
