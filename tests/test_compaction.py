from __future__ import annotations

from miniagent.agent import Agent
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation, Status
from miniagent.events import (
    ActionEvent,
    CondensationEvent,
    ErrorEvent,
    MessageEvent,
    ObservationEvent,
    RepoInstructionsEvent,
    WorkspaceSketchEvent,
)
from miniagent.llm import ContextOverflow, LLMResponse
from miniagent.tools.base import ToolRegistry
from miniagent.tools.finish import FinishTool
from miniagent.tools.terminal import TerminalTool
from tests.test_agent_history import EchoSandbox
from tests.test_sandbox_failures import SafePolicy


class WindowLLM:
    model = "scripted"

    def __init__(self, window: int, responses: list) -> None:
        self.window = window
        self.responses = responses
        self.seen: list[tuple[str, list[dict]]] = []

    def context_window(self) -> int:
        return self.window

    def count_tokens(self, messages, tools=None) -> int:
        return sum(len(str(m.get("content") or "")) for m in messages) // 4

    def complete(self, messages, tools=None, phase="agent", tool_choice="auto"):
        if phase == "finish_nudge":
            return LLMResponse()
        self.seen.append((phase, messages))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _conversation(llm) -> Conversation:
    agent = Agent(
        llm=llm,
        tools=ToolRegistry([TerminalTool(), FinishTool()]),
        policy=SafePolicy(),
    )
    return Conversation(
        agent=agent,
        sandbox=EchoSandbox(),
        confirm_policy=ConfirmPolicy("full"),
        stuck_detection=False,
    )


def _history(conversation: Conversation, turns: int, output_chars: int) -> None:
    for i in range(turns):
        conversation.add_event(MessageEvent(role="user", text=f"task {i}"))
        conversation.add_event(
            ActionEvent(tool_name="terminal", arguments={"command": f"cmd {i}"}, tool_call_id=f"c{i}")
        )
        conversation.add_event(
            ObservationEvent(tool_name="terminal", tool_call_id=f"c{i}", content="x" * output_chars)
        )
        conversation.add_event(MessageEvent(role="assistant", text=f"done {i}"))


def _pairs_intact(messages: list[dict]) -> bool:
    for index, message in enumerate(messages):
        for call in message.get("tool_calls") or []:
            following = messages[index + 1 :]
            if not any(m.get("tool_call_id") == call["id"] for m in following):
                return False
    return True


def test_pruning_old_outputs_alone_can_bring_the_prompt_under_target():
    llm = WindowLLM(40_000, [LLMResponse(text="ok")])
    conversation = _conversation(llm)
    _history(conversation, 14, 10_000)
    conversation.send_message("next")
    conversation.run()

    [compaction] = [e for e in conversation.events if isinstance(e, CondensationEvent)]
    assert compaction.pruned_only and compaction.elided_event_ids
    phase, messages = llm.seen[-1]
    assert phase == "step"
    assert any("middle pruned" in str(m.get("content")) for m in messages)
    assert not any(p == "condense" for p, _ in llm.seen)
    assert _pairs_intact(messages)


def test_summary_replaces_old_events_and_keeps_pairs_intact():
    llm = WindowLLM(
        6_000,
        [LLMResponse(text="## Primary request\nkeep going"), LLMResponse(text="ok")],
    )
    conversation = _conversation(llm)
    _history(conversation, 14, 1_500)
    conversation.send_message("next")
    conversation.run()

    summaries = [
        e for e in conversation.events if isinstance(e, CondensationEvent) and not e.pruned_only
    ]
    assert summaries and summaries[0].replaced_event_ids
    condense_phase, condense_messages = llm.seen[0]
    assert condense_phase == "condense"
    assert "Primary request" in condense_messages[-1]["content"]
    _, step_messages = llm.seen[-1]
    assert any("[conversation summary]" in str(m.get("content")) for m in step_messages)
    assert _pairs_intact(step_messages)


def test_repo_instructions_and_sketch_survive_a_summary():
    llm = WindowLLM(
        6_000,
        [LLMResponse(text="## Primary request\nkeep going"), LLMResponse(text="ok")],
    )
    conversation = _conversation(llm)
    instructions = RepoInstructionsEvent(paths=["AGENTS.md"], content="Use uv, never pip.")
    sketch = WorkspaceSketchEvent(content="## Tracked files\nsrc/app.py")
    conversation.add_event(sketch)
    conversation.add_event(instructions)
    _history(conversation, 14, 1_500)
    conversation.send_message("next")
    conversation.run()

    [summary] = [
        e for e in conversation.events if isinstance(e, CondensationEvent) and not e.pruned_only
    ]
    assert summary.replaced_event_ids
    assert instructions.id not in summary.replaced_event_ids
    assert sketch.id not in summary.replaced_event_ids
    _, step_messages = llm.seen[-1]
    contents = [str(m.get("content")) for m in step_messages]
    assert any("Use uv, never pip." in c for c in contents)
    assert any("src/app.py" in c for c in contents)


def _pruned_step_messages(observation: ObservationEvent) -> list[dict]:
    llm = WindowLLM(1_000_000, [LLMResponse(text="ok")])
    conversation = _conversation(llm)
    conversation.add_event(MessageEvent(role="user", text="look"))
    conversation.add_event(
        ActionEvent(tool_name="terminal", arguments={"command": "cat log"}, tool_call_id="c1")
    )
    conversation.add_event(observation)
    conversation.add_event(
        CondensationEvent(
            summary="",
            replaced_event_ids=[],
            elided_event_ids=[observation.id],
            trigger="threshold",
            pruned_only=True,
        )
    )
    conversation.send_message("next")
    conversation.run()
    _, messages = llm.seen[-1]
    return messages


def test_pruned_output_keeps_head_and_tail_and_names_the_spill_file():
    content = "H" * 3_000 + "M" * 2_000 + "T" * 1_200
    observation = ObservationEvent(
        tool_name="terminal",
        tool_call_id="c1",
        content=content,
        details={"spill_path": ".miniagent/outputs/c1.txt", "full_chars": 20_000},
    )
    messages = _pruned_step_messages(observation)

    [sent] = [m["content"] for m in messages if m.get("tool_call_id") == "c1"]
    head, marker, tail = sent.split("\n")
    assert head == "H" * 1_500
    assert tail == "T" * 1_000
    assert "20,000 chars, middle pruned" in marker
    assert "Full output: .miniagent/outputs/c1.txt" in marker
    assert observation.content == content


def test_overflow_forces_one_compaction_and_retry():
    llm = WindowLLM(
        1_000_000,
        [
            ContextOverflow("prompt is too long"),
            LLMResponse(text="## Primary request\nsummary"),
            LLMResponse(text="recovered"),
        ],
    )
    conversation = _conversation(llm)
    _history(conversation, 14, 500)
    conversation.send_message("next")
    conversation.run()

    assert conversation.status == Status.IDLE
    [summary] = [e for e in conversation.events if isinstance(e, CondensationEvent)]
    assert summary.trigger == "overflow"
    assert [p for p, _ in llm.seen] == ["step", "condense", "step"]


def test_a_second_overflow_ends_the_step_with_an_error():
    llm = WindowLLM(
        1_000_000,
        [
            ContextOverflow("too long"),
            LLMResponse(text="## Primary request\nsummary"),
            ContextOverflow("still too long"),
        ],
    )
    conversation = _conversation(llm)
    _history(conversation, 14, 500)
    conversation.send_message("next")
    conversation.run()

    assert conversation.status == Status.ERROR
    errors = [e for e in conversation.events if isinstance(e, ErrorEvent)]
    assert errors[-1].message == "Context window exceeded after compaction"


def test_an_overflowing_summary_request_is_shrunk_instead_of_failing_the_step():
    llm = WindowLLM(
        1_000_000,
        [
            ContextOverflow("prompt is too long"),
            ContextOverflow("summary request is too long too"),
            LLMResponse(text="## Primary request\nsummary"),
            LLMResponse(text="recovered"),
        ],
    )
    conversation = _conversation(llm)
    _history(conversation, 14, 5_000)
    conversation.send_message("the newest request stays verbatim")
    conversation.run()

    assert conversation.status == Status.IDLE
    assert [p for p, _ in llm.seen] == ["step", "condense", "condense", "step"]
    first, shrunk = (messages for phase, messages in llm.seen if phase == "condense")
    def longest(messages):
        return max(len(str(m.get("content") or "")) for m in messages[1:-1])

    assert longest(first) > 4_000 and longest(shrunk) < 2_200
    assert all("the newest request stays verbatim" not in str(m.get("content")) for m in first)
    retried = llm.seen[-1][1]
    assert any(m.get("content") == "the newest request stays verbatim" for m in retried)


def test_a_reply_cut_off_at_the_output_limit_is_not_taken_as_the_answer():
    llm = WindowLLM(
        1_000_000,
        [
            LLMResponse(text="Here is the full rewrite of the fi", truncated=True),
            LLMResponse(text="Done in smaller pieces."),
        ],
    )
    conversation = _conversation(llm)
    conversation.send_message("rewrite the file")
    conversation.run()

    assert conversation.status == Status.IDLE
    assert [p for p, _ in llm.seen] == ["step", "step"]
    retried = llm.seen[-1][1]
    assert any("hit the output token limit" in str(m.get("content")) for m in retried)
    assert conversation.events[-1].text == "Done in smaller pieces."


def test_three_cut_off_replies_in_a_row_end_the_run():
    llm = WindowLLM(
        1_000_000,
        [LLMResponse(text="partial", truncated=True) for _ in range(3)],
    )
    conversation = _conversation(llm)
    conversation.send_message("rewrite everything")
    conversation.run()

    assert conversation.status == Status.ERROR
    assert "cut off at the output token limit 3 times" in conversation.events[-1].message
