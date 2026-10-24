from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

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
from tests.test_sandbox_failures import SafePolicy


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
    )
    sandbox = LocalSandbox(str(workspace))
    conversation = Conversation(
        agent=agent,
        sandbox=sandbox,
        confirm_policy=ConfirmPolicy("full"),
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


def test_large_output_is_spilled_outside_the_workspace(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    conversation, sandbox = _run(repo, "seq 1 20000")
    spill = Path(SPILL_DIR) / conversation.id / "outputs" / "call_big.txt"
    try:
        observation = _observation(conversation)
        assert observation.details["spill_path"] == str(spill)
        assert str(spill) in observation.content
        assert len(observation.content) < SPILL_PREVIEW_CHARS + 1_000
        assert spill.read_text().splitlines()[-1] == "20000"
        assert sorted(p.name for p in repo.iterdir()) == [".git"]
    finally:
        shutil.rmtree(spill.parents[1], ignore_errors=True)
