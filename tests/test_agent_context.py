from __future__ import annotations

from miniagent.agent import Agent, _file_sketch
from miniagent.conversation import Conversation
from miniagent.events import WorkspaceSketchEvent
from miniagent.llm import LLMResponse
from miniagent.tools.base import ToolRegistry


class ScriptedLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = responses
        self.calls: list[list[dict]] = []

    def complete(self, messages, tools=None):
        self.calls.append(messages)
        if not self._responses:
            return LLMResponse(text="done")
        return self._responses.pop(0)

    def count_tokens(self, messages) -> int:
        return 0


def test_repository_instructions_are_not_auto_injected(sandbox):
    sandbox.write_file("AGENTS.md", "Run tests with `uv run pytest`.")
    agent = Agent(llm=ScriptedLLM([]), tools=ToolRegistry())  # type: ignore[arg-type]
    conversation = Conversation(agent=agent, sandbox=sandbox)
    system = agent._build_messages(conversation, sandbox)[0]["content"]
    assert "uv run pytest" not in system


# --- file sketch ------------------------------------------------------------------


def test_file_sketch_outside_git_repo(sandbox):
    assert _file_sketch(sandbox) == ""


def test_file_sketch_lists_tracked_files(sandbox):
    sandbox.write_file("a.py", "x = 1")
    sandbox.write_file("src/b.py", "y = 2")
    sandbox.run_command("git init -q && git add -A")
    block = _file_sketch(sandbox)
    assert block.startswith("\n\n## Tracked files (git ls-files)")
    assert "a.py" in block
    assert "src/b.py" in block


def test_workspace_sketch_is_added_once(sandbox):
    sandbox.write_file("a.py", "x = 1")
    sandbox.run_command("git init -q && git add -A")
    llm = ScriptedLLM([LLMResponse(text="first"), LLMResponse(text="second")])
    agent = Agent(llm=llm, tools=ToolRegistry())  # type: ignore[arg-type]
    conversation = Conversation(agent=agent, sandbox=sandbox)

    conversation.send_message("first")
    conversation.run()
    conversation.send_message("second")
    conversation.run()

    sketches = [
        event for event in conversation.events if isinstance(event, WorkspaceSketchEvent)
    ]
    assert len(sketches) == 1
    assert "a.py" in sketches[0].content
