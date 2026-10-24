from __future__ import annotations

from miniagent.agent import Agent
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation, Status
from miniagent.events import ObservationEvent
from miniagent.llm import LLMResponse, ToolCall
from miniagent.prompts import FINISH_CHECKLIST_PROMPT
from miniagent.sandbox.local import LocalSandbox
from miniagent.tools.base import ToolRegistry
from miniagent.tools.file_edit import FileEditTool
from miniagent.tools.finish import FinishTool
from miniagent.tools.terminal import TerminalTool
from tests.test_agent_history import EchoSandbox, QueueLLM
from tests.test_sandbox_failures import SafePolicy


def _create(path: str) -> LLMResponse:
    return LLMResponse(
        tool_calls=[
            ToolCall(
                id=f"create-{path}",
                name="file_edit",
                arguments={"command": "create", "path": path, "content": "x\n"},
            )
        ]
    )


def _finish(call_id: str) -> LLMResponse:
    return LLMResponse(
        tool_calls=[ToolCall(id=call_id, name="finish", arguments={"message": "Done."})]
    )


def _run(*responses: LLMResponse) -> Conversation:
    agent = Agent(
        llm=QueueLLM(*responses),
        tools=ToolRegistry([TerminalTool(), FileEditTool(), FinishTool()]),
        policy=SafePolicy(),
    )
    conversation = Conversation(
        agent=agent,
        sandbox=EchoSandbox(),
        confirm_policy=ConfirmPolicy("full"),
        stuck_detection=False,
    )
    conversation.send_message("go")
    conversation.run()
    return conversation


def _finish_errors(conversation: Conversation) -> list[str]:
    return [
        e.content
        for e in conversation.events
        if isinstance(e, ObservationEvent) and e.tool_name == "finish" and e.error
    ]


def test_a_docs_only_change_can_finish_without_a_check():
    conversation = _run(_create("NOTES.md"), _finish("f1"))

    assert conversation.status == Status.FINISHED
    assert _finish_errors(conversation) == []


def test_a_code_change_still_needs_verification_before_finishing():
    conversation = _run(_create("app.py"), _finish("f1"), LLMResponse(text="stuck"))

    assert conversation.status == Status.IDLE
    [error] = _finish_errors(conversation)
    assert error.startswith("Verification required before finishing")


def test_the_headless_finish_ends_the_run_only_when_called_right_after_its_checklist(tmp_path):
    agent = Agent(
        llm=QueueLLM(
            _finish("f1"),
            LLMResponse(
                tool_calls=[ToolCall(id="b1", name="terminal", arguments={"command": "ls"})]
            ),
            _finish("f2"),
            LLMResponse(
                tool_calls=[ToolCall(id="f3", name="finish", arguments={"message": "Checked."})]
            ),
        ),
        tools=ToolRegistry([TerminalTool(), FinishTool(checklist=FINISH_CHECKLIST_PROMPT)]),
        policy=SafePolicy(),
    )
    conversation = Conversation(
        agent=agent,
        sandbox=LocalSandbox(str(tmp_path)),
        confirm_policy=ConfirmPolicy("full"),
        stuck_detection=False,
    )
    conversation.send_message("go")
    try:
        conversation.run()
    finally:
        agent.close()

    finishes = [
        e.content
        for e in conversation.events
        if isinstance(e, ObservationEvent) and e.tool_name == "finish"
    ]
    assert conversation.status == Status.FINISHED
    assert finishes == [FINISH_CHECKLIST_PROMPT, FINISH_CHECKLIST_PROMPT, "Checked."]
