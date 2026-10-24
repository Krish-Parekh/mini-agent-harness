from __future__ import annotations

from miniagent.agent import Agent
from miniagent.conversation import Conversation
from miniagent.events import (
    CondensationEvent,
    MemoryIndexEvent,
    MessageEvent,
    RepoInstructionsEvent,
    WorkspaceSketchEvent,
)
from miniagent.llm import LLM
from miniagent.sandbox.local import LocalSandbox
from miniagent.tools.base import ToolRegistry
from miniagent.tools.finish import FinishTool
from miniagent.tools.mcp import McpTool
from miniagent.tools.terminal import TerminalTool


def _conversation(tmp_path) -> Conversation:
    tracker = McpTool(
        connection="tracker",
        remote_name="search",
        description="Search the issue tracker.",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        invoke=lambda name, arguments: "",
        read_only=True,
    )
    agent = Agent(
        llm=LLM(model="anthropic/claude-sonnet-5-5"),
        tools=ToolRegistry([TerminalTool(), FinishTool(), tracker]),
        policy=object(),
    )
    agent.skills_block = "- review: check the diff before finishing"
    agent.mcp_instructions = {"tracker": "Search before you create an issue."}
    conversation = Conversation(agent, LocalSandbox(str(tmp_path)))
    conversation.events += [
        RepoInstructionsEvent(paths=["AGENTS.md"], content="# AGENTS.md\nRun the tests. " * 40),
        MemoryIndexEvent(content="/memories/user/style.md: plain English"),
        WorkspaceSketchEvent(content="src/app.py\ntests/test_app.py"),
        MessageEvent(role="user", text="Fix the failing test in tests/test_app.py"),
        MessageEvent(role="assistant", text="Reading the test first."),
    ]
    return conversation


def test_categories_split_the_exact_request_by_source(tmp_path):
    conversation = _conversation(tmp_path)
    agent = conversation.agent

    window = agent.context_window(conversation, conversation.sandbox)

    tokens = {c.name: c.tokens for c in window.categories}
    sent = agent.llm.count_tokens(
        agent._build_messages(conversation, conversation.sandbox), agent.tools.all()
    )
    assert window.used == sent
    assert sum(tokens.values()) == sent
    assert all(tokens[name] > 0 for name in tokens)
    assert tokens["Rules"] > tokens["Workspace"]
    assert window.limit == agent.llm.context_window()


def test_compacted_rules_stop_counting(tmp_path):
    conversation = _conversation(tmp_path)
    rules = conversation.events[0]
    before = {
        c.name: c.tokens
        for c in conversation.agent.context_window(conversation, conversation.sandbox).categories
    }

    conversation.events.append(
        CondensationEvent(summary="Earlier: read AGENTS.md.", replaced_event_ids=[rules.id])
    )
    after = {
        c.name: c.tokens
        for c in conversation.agent.context_window(conversation, conversation.sandbox).categories
    }

    assert before["Rules"] > 0
    assert after["Rules"] == 0
