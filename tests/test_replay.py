from __future__ import annotations

import subprocess

import pytest

from miniagent.agent import Agent
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation, Status
from miniagent.events import ActionEvent, MessageEvent
from miniagent.llm import LLM
from miniagent.policy import PolicyClassifier
from miniagent.sandbox.local import LocalSandbox
from miniagent.tools.base import ToolRegistry
from miniagent.tools.bash import BashTool
from miniagent.tools.file_edit import FileEditTool
from miniagent.tools.finish import FinishTool
from miniagent.tools.search import GlobTool, GrepTool
from tests.replay import cassette  # noqa: F401

MODEL = "anthropic/claude-haiku-5-5"


def _conversation(workspace, confirm: str = "never") -> Conversation:
    agent = Agent(
        llm=LLM(model=MODEL, max_tokens=4096),
        tools=ToolRegistry([BashTool(), FileEditTool(), GrepTool(), GlobTool(), FinishTool()]),
        policy=PolicyClassifier(LLM(model=MODEL, temperature=0.0, max_tokens=1024)),
    )
    return Conversation(
        agent=agent,
        sandbox=LocalSandbox(str(workspace)),
        confirm_policy=ConfirmPolicy(confirm),
        stuck_detection=False,
    )


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "config.py").write_text("RETRY_LIMIT = 7\nTIMEOUT_S = 30\n")
    (tmp_path / "greet.py").write_text("def greet(name):\n    return f'Hello, {name}'\n")
    (tmp_path / "test_greet.py").write_text(
        "from greet import greet\n\n\ndef test_greet():\n    assert greet('Ada') == 'Hi, Ada'\n"
    )
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "out.txt").write_text("artifact\n")
    return tmp_path


def _final_text(conversation: Conversation) -> str:
    finishes = [
        e.arguments.get("message", "")
        for e in conversation.events
        if isinstance(e, ActionEvent) and e.tool_name == "finish"
    ]
    replies = [e.text for e in conversation.events if isinstance(e, MessageEvent) and e.role == "assistant"]
    return " ".join([*finishes, *replies])


def test_read_and_answer(tmp_path, cassette):  # noqa: F811
    conversation = _conversation(_repo(tmp_path))
    conversation.send_message(
        "What is RETRY_LIMIT set to in this repository? Do not change any files. Answer, then finish."
    )
    conversation.run()
    assert "7" in _final_text(conversation)
    assert (tmp_path / "config.py").read_text() == "RETRY_LIMIT = 7\nTIMEOUT_S = 30\n"


def test_edit_and_verify(tmp_path, cassette):  # noqa: F811
    conversation = _conversation(_repo(tmp_path))
    conversation.send_message(
        "The test in test_greet.py fails. Fix greet.py so it passes, run "
        "`python -m pytest -q test_greet.py` to verify, then finish."
    )
    conversation.run()
    assert "Hi, {name}" in (tmp_path / "greet.py").read_text()
    commands = [
        e.arguments.get("command", "")
        for e in conversation.events
        if isinstance(e, ActionEvent) and e.tool_name == "bash"
    ]
    assert any("pytest" in command for command in commands)


def test_a_destructive_command_waits_for_approval(tmp_path, cassette):  # noqa: F811
    conversation = _conversation(_repo(tmp_path), confirm="risky")
    conversation.send_message("Delete the build directory with `rm -rf build`, then finish.")
    conversation.run()
    assert conversation.status == Status.WAITING_FOR_CONFIRMATION
    assert "rm -rf build" in conversation.pending_action().arguments["command"]
    assert (tmp_path / "build" / "out.txt").exists()


def test_a_cassette_with_a_secret_in_it_is_never_written(tmp_path, monkeypatch):
    from tests.replay import Cassette

    monkeypatch.setenv("FAKE_PROVIDER_API_KEY", "supersecretvalue123")
    tape = Cassette.__new__(Cassette)
    tape.path = tmp_path / "leak.json"
    tape.entries = [{"response": {"echo": "supersecretvalue123"}}]
    with pytest.raises(AssertionError, match="contains a secret"):
        tape.save()
    assert not tape.path.exists()
