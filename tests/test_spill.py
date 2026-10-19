from __future__ import annotations

import subprocess

from miniagent.agent import SPILL_DIR, SPILL_PREVIEW_CHARS, Agent
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation
from miniagent.events import ObservationEvent
from miniagent.llm import LLMResponse, ToolCall
from miniagent.sandbox.local import LocalSandbox
from miniagent.tools.base import ToolRegistry
from miniagent.tools.bash import BashTool
from miniagent.tools.finish import FinishTool
from tests.test_agent_history import QueueLLM
from tests.test_sandbox_failures import DefaultRoute, SafePolicy


def _run(workspace, command: str) -> tuple[Conversation, LocalSandbox]:
    llm = QueueLLM(
        LLMResponse(
            tool_calls=[ToolCall(id="call_big", name="bash", arguments={"command": command})]
        ),
        LLMResponse(text="done"),
    )
    agent = Agent(
        llm=llm,
        tools=ToolRegistry([BashTool(), FinishTool()]),
        policy=SafePolicy(),
        task_router=DefaultRoute(),
    )
    sandbox = LocalSandbox(str(workspace))
    conversation = Conversation(
        agent=agent,
        sandbox=sandbox,
        confirm_policy=ConfirmPolicy("never"),
        stuck_detection=False,
    )
    conversation.send_message("print a lot")
    conversation.run()
    return conversation, sandbox


def _observation(conversation: Conversation) -> ObservationEvent:
    return next(e for e in conversation.events if isinstance(e, ObservationEvent))


def _git_repo(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def test_large_output_is_spilled_and_kept_out_of_git(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    conversation, sandbox = _run(repo, "seq 1 20000")

    observation = _observation(conversation)
    path = f"{SPILL_DIR}/call_big.txt"
    assert observation.details["spill_path"] == path
    assert path in observation.content
    assert len(observation.content) < SPILL_PREVIEW_CHARS + 1_000
    assert "20000" in sandbox.read_file(path)
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert ".miniagent" not in status


def test_small_output_is_inlined(tmp_path):
    conversation, _ = _run(_git_repo(tmp_path / "repo"), "echo hi")
    observation = _observation(conversation)
    assert "spill_path" not in (observation.details or {})
    assert "hi" in observation.content


def test_spill_failure_falls_back_to_a_clip(tmp_path, monkeypatch):
    def refuse(self, path, content):
        raise OSError("read-only file system")

    monkeypatch.setattr(LocalSandbox, "write_file", refuse)
    conversation, _ = _run(tmp_path, "seq 1 20000")
    observation = _observation(conversation)
    assert observation.content.endswith("[full output unavailable]")
    assert "spill_path" not in (observation.details or {})
