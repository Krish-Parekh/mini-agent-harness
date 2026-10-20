from __future__ import annotations

from miniagent.conversation import Status
from miniagent.events import ActionEvent, MessageEvent
from miniagent.llm import LLMResponse, ToolCall
from tests.test_agent_history import _conversation


class NudgeLLM:
    model = "scripted"

    def __init__(self, *responses: LLMResponse) -> None:
        self.responses = list(responses)
        self.phases: list[str] = []
        self.seen: list[list[dict]] = []

    def context_window(self) -> int:
        return 1_000_000

    def count_tokens(self, messages, tools=None) -> int:
        return 0

    def complete(self, messages, tools=None, phase="agent"):
        self.phases.append(phase)
        self.seen.append(messages)
        return self.responses.pop(0)


def _finish(message: str) -> LLMResponse:
    return LLMResponse(
        tool_calls=[ToolCall(id="f1", name="finish", arguments={"message": message})]
    )


def _assistant_texts(conversation) -> list[str]:
    return [
        e.text
        for e in conversation.events
        if isinstance(e, MessageEvent) and e.role == "assistant"
    ]


def test_a_text_only_reply_is_nudged_once_and_finishes():
    llm = NudgeLLM(LLMResponse(text="The answer is 42."), _finish("The answer is 42."))
    conversation, _ = _conversation(llm)
    conversation.send_message("what is the answer?")
    conversation.run()

    assert conversation.status == Status.FINISHED
    assert llm.phases == ["step", "finish_nudge"]
    assert llm.seen[-1][-2] == {"role": "assistant", "content": "The answer is 42."}
    assert _assistant_texts(conversation) == []


def test_a_second_text_only_reply_ends_the_turn_without_looping():
    llm = NudgeLLM(LLMResponse(text="Still thinking."), LLMResponse(text="Done."))
    conversation, _ = _conversation(llm)
    conversation.send_message("hi")
    conversation.run()

    assert conversation.status == Status.IDLE
    assert llm.phases == ["step", "finish_nudge"]
    assert _assistant_texts(conversation) == ["Still thinking."]


def test_the_nudge_can_continue_the_task_with_another_tool():
    bash = LLMResponse(
        tool_calls=[ToolCall(id="b1", name="bash", arguments={"command": "ls"})]
    )
    llm = NudgeLLM(
        LLMResponse(text="Let me look."), bash, _finish("Listed the files.")
    )
    conversation, sandbox = _conversation(llm)
    conversation.send_message("list files")
    conversation.run()

    assert conversation.status == Status.FINISHED
    assert llm.phases == ["step", "finish_nudge", "step"]
    assert sandbox.commands[-1] == "ls"
    assert [e.tool_name for e in conversation.events if isinstance(e, ActionEvent)] == [
        "bash",
        "finish",
    ]
