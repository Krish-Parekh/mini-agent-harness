from __future__ import annotations

from miniagent.events import RepoInstructionsEvent
from miniagent.llm import LLMResponse
from tests.test_agent_history import QueueLLM
from miniagent.agent import Agent
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation
from miniagent.sandbox.local import LocalSandbox
from miniagent.tools.base import ToolRegistry
from miniagent.tools.finish import FinishTool
from tests.test_sandbox_failures import SafePolicy


def _run(workspace) -> tuple[Conversation, QueueLLM]:
    llm = QueueLLM(LLMResponse(text="ok"), LLMResponse(text="ok again"))
    agent = Agent(
        llm=llm,
        tools=ToolRegistry([FinishTool()]),
        policy=SafePolicy(),
    )
    conversation = Conversation(
        agent=agent,
        sandbox=LocalSandbox(str(workspace)),
        confirm_policy=ConfirmPolicy("never"),
        stuck_detection=False,
    )
    conversation.send_message("hi")
    conversation.run()
    return conversation, llm


def _events(conversation):
    return [e for e in conversation.events if isinstance(e, RepoInstructionsEvent)]


def test_agents_md_reaches_the_model(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Always run `make check`.")
    conversation, llm = _run(tmp_path)
    [event] = _events(conversation)
    assert event.paths == ["AGENTS.md"]
    assert any("Always run `make check`." in str(m["content"]) for m in llm.seen[0])


def test_both_files_are_combined_once(tmp_path):
    (tmp_path / "AGENTS.md").write_text("A rules")
    (tmp_path / "CLAUDE.md").write_text("C rules")
    conversation, _ = _run(tmp_path)
    conversation.send_message("again")
    conversation.run()
    [event] = _events(conversation)
    assert event.paths == ["AGENTS.md", "CLAUDE.md"]
    assert "A rules" in event.content and "C rules" in event.content
