from __future__ import annotations

import threading

from miniagent.agent import Agent
from miniagent.classification import StaticTaskClassifier, TaskRoute
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation, Status
from miniagent.events import (
    CondensationEvent,
    ErrorEvent,
    LLMUsageEvent,
    MessageEvent,
    ObservationEvent,
)
from miniagent.llm import LLMResponse, TokenUsage, ToolCall
from miniagent.policy import CommandPolicy
from miniagent.tools.ask import AskUserTool
from miniagent.tools.base import ToolRegistry
from miniagent.tools.bash import BashTool
from miniagent.tools.fanout import FanoutAction, FanoutTask, FanoutTool, ReadOnlyFileEditTool
from miniagent.tools.file_edit import FileEditAction, FileEditTool
from miniagent.tools.finish import FinishTool
from miniagent.tools.plan import Plan, PlanStep, PresentPlanTool


class ScriptedLLM:
    def __init__(self, responses: list[LLMResponse], tokens: int = 0) -> None:
        self._responses = responses
        self._tokens = tokens
        self._lock = threading.Lock()
        self.calls: list[list[dict]] = []
        self.model = "test-model"

    def complete(self, messages, tools=None):
        with self._lock:
            self.calls.append(messages)
            if not self._responses:
                return LLMResponse(text="")
            return self._responses.pop(0)

    def count_tokens(self, messages) -> int:
        return self._tokens


class StaticPolicy:
    def __init__(
        self,
        bash: dict[str, CommandPolicy] | None = None,
        finish: dict[str, CommandPolicy] | None = None,
    ) -> None:
        self.bash = bash or {}
        self.finish = finish or {}

    def classify_bash(self, command: str) -> CommandPolicy:
        return self.bash.get(
            command,
            CommandPolicy(
                risk="safe",
                read_only=False,
                is_verification=False,
                reason="test default",
            ),
        )

    def classify_finish_message(self, message: str) -> CommandPolicy:
        return self.finish.get(message, CommandPolicy(risk="safe", read_only=True))


def call(name: str, arguments: dict, id: str = "call") -> ToolCall:
    return ToolCall(id=id, name=name, arguments=arguments)


def agent_with(
    responses: list[LLMResponse],
    tools: list,
    tokens: int = 0,
    policy: StaticPolicy | None = None,
    route: TaskRoute = TaskRoute.DEFAULT,
) -> Agent:
    return Agent(
        llm=ScriptedLLM(responses, tokens=tokens),  # type: ignore[arg-type]
        tools=ToolRegistry(tools),
        policy=policy or StaticPolicy(),
        task_router=StaticTaskClassifier(route),
    )


def test_conversation_run_finishes_with_finish_tool(sandbox):
    agent = agent_with(
        [LLMResponse(tool_calls=[call("finish", {"message": "done"})])],
        [FinishTool()],
    )
    conversation = Conversation(agent=agent, sandbox=sandbox)

    conversation.send_message("say done")
    conversation.run()

    assert conversation.status == Status.FINISHED
    assert any(
        isinstance(event, ObservationEvent)
        and event.tool_name == "finish"
        and event.content == "done"
        for event in conversation.events
    )


def test_finish_rejected_when_bundled_with_other_tools(sandbox):
    llm = ScriptedLLM(
        [
            LLMResponse(
                tool_calls=[
                    call("bash", {"command": "echo hi"}, "bash-1"),
                    call("finish", {"message": "done"}, "finish-1"),
                ]
            ),
            LLMResponse(tool_calls=[call("finish", {"message": "all done"}, "finish-2")]),
        ]
    )
    agent = Agent(
        llm=llm,  # type: ignore[arg-type]
        tools=ToolRegistry([BashTool(), FinishTool()]),
        policy=StaticPolicy(bash={"echo hi": CommandPolicy(risk="safe", read_only=True)}),
        task_router=StaticTaskClassifier(),
    )
    conversation = Conversation(agent=agent, sandbox=sandbox)

    conversation.send_message("run and finish")
    conversation.run()

    assert conversation.status == Status.FINISHED
    rejected = [
        event
        for event in conversation.events
        if isinstance(event, ObservationEvent)
        and event.tool_name == "finish"
        and event.error
    ]
    assert len(rejected) == 1
    assert "together with other tools" in rejected[0].content
    assert any(
        isinstance(event, ObservationEvent)
        and event.tool_name == "finish"
        and event.content == "all done"
        and not event.error
        for event in conversation.events
    )


def test_conversation_generates_best_effort_answer_after_max_iterations(sandbox):
    agent = agent_with(
        [
            LLMResponse(
                tool_calls=[
                    call("bash", {"command": "printf still-running", "timeout": 5}, f"b{i}")
                ]
            )
            for i in range(2)
        ]
        + [
            LLMResponse(
                text="I reached the step limit after confirming the command still runs."
            )
        ],
        [BashTool()],
    )
    conversation = Conversation(agent=agent, sandbox=sandbox, max_iterations=2)

    conversation.send_message("loop")
    conversation.run()

    assert conversation.status == Status.IDLE
    assert isinstance(conversation.events[-1], MessageEvent)
    assert "step limit" in conversation.events[-1].text
    assert len(agent.llm.calls) == 3  # type: ignore[attr-defined]
    assert "maximum number of agent loop iterations" in agent.llm.calls[-1][-1][  # type: ignore[attr-defined]
        "content"
    ]


def test_ask_user_pauses_as_idle(sandbox):
    agent = agent_with(
        [
            LLMResponse(
                tool_calls=[
                    call(
                        "ask_user",
                        {
                            "questions": [
                                {
                                    "question": "Which option?",
                                    "header": "Choice",
                                    "options": ["A", "B"],
                                }
                            ]
                        },
                    )
                ]
            )
        ],
        [AskUserTool()],
    )
    conversation = Conversation(agent=agent, sandbox=sandbox)

    conversation.send_message("ask")
    conversation.run()

    assert conversation.status == Status.IDLE


def test_present_plan_stores_plan_and_keeps_plan_mode(sandbox):
    agent = agent_with(
        [
            LLMResponse(
                tool_calls=[
                    call(
                        "present_plan",
                        {
                            "title": "Do work",
                            "steps": [
                                {
                                    "title": "Inspect files",
                                    "files": ["miniagent/agent.py"],
                                    "description": "Understand the loop.",
                                }
                            ],
                        },
                    )
                ]
            )
        ],
        [PresentPlanTool()],
    )
    conversation = Conversation(agent=agent, sandbox=sandbox)

    conversation.send_message("plan this", plan_mode=True)
    conversation.run()

    assert conversation.status == Status.IDLE
    assert conversation.plan_mode is True
    assert conversation.plan is not None
    assert conversation.plan.title == "Do work"


def test_plan_mode_blocks_mutating_file_edit(sandbox):
    agent = agent_with(
        [
            LLMResponse(
                tool_calls=[
                    call(
                        "file_edit",
                        {"command": "create", "path": "x.txt", "content": "nope"},
                        "edit",
                    )
                ]
            ),
            LLMResponse(
                tool_calls=[
                    call("present_plan", {"title": "Stop", "steps": []}, "plan")
                ]
            ),
        ],
        [FileEditTool(), PresentPlanTool()],
    )
    conversation = Conversation(agent=agent, sandbox=sandbox, max_iterations=2)

    conversation.send_message("plan", plan_mode=True)
    conversation.run()

    assert conversation.status == Status.IDLE
    assert sandbox.list_files(".") == []
    assert any(
        isinstance(event, ObservationEvent)
        and event.tool_name == "file_edit"
        and event.error
        and "Plan mode is active" in event.content
        for event in conversation.events
    )


def test_confirmation_approve_resumes_pending_action(sandbox):
    agent = agent_with(
        [
            LLMResponse(
                tool_calls=[
                    call("file_edit", {"command": "view", "path": "/tmp/nope"}, "view")
                ]
            ),
            LLMResponse(tool_calls=[call("finish", {"message": "done"}, "finish")]),
        ],
        [FileEditTool(), FinishTool()],
    )
    conversation = Conversation(
        agent=agent,
        sandbox=sandbox,
        confirm_policy=ConfirmPolicy("risky"),
    )

    conversation.send_message("run")
    conversation.run()
    assert conversation.status == Status.WAITING_FOR_CONFIRMATION

    conversation.approve()

    assert conversation.status == Status.FINISHED
    assert any(
        isinstance(event, ObservationEvent)
        and event.tool_name == "file_edit"
        and event.error
        and "File not found" in event.content
        for event in conversation.events
    )


def test_confirmation_reject_records_error_and_continues(sandbox):
    agent = agent_with(
        [
            LLMResponse(
                tool_calls=[
                    call("file_edit", {"command": "view", "path": "/tmp/nope"}, "view")
                ]
            ),
            LLMResponse(tool_calls=[call("finish", {"message": "done"}, "finish")]),
        ],
        [FileEditTool(), FinishTool()],
    )
    conversation = Conversation(
        agent=agent,
        sandbox=sandbox,
        confirm_policy=ConfirmPolicy("risky"),
    )

    conversation.send_message("run")
    conversation.run()
    conversation.reject("No thanks.")

    assert conversation.status == Status.FINISHED
    assert any(
        isinstance(event, ObservationEvent)
        and event.tool_name == "file_edit"
        and event.error
        and "No thanks" in event.content
        for event in conversation.events
    )


def test_repeated_identical_calls_abort(sandbox):
    responses = [
        LLMResponse(
            tool_calls=[
                call("bash", {"command": "printf repeat", "timeout": 5}, f"bash-{i}")
            ]
        )
        for i in range(6)
    ]
    agent = agent_with(responses, [BashTool()])
    conversation = Conversation(agent=agent, sandbox=sandbox, max_iterations=10)

    conversation.send_message("repeat")
    conversation.run()

    assert conversation.status == Status.STUCK
    last = conversation.events[-1]
    assert last.kind == "error"
    assert "stuck:" in last.message
    assert "repeated the same bash call and result" in last.message


def test_same_result_different_calls_does_not_abort(sandbox):
    responses = [
        LLMResponse(
            tool_calls=[
                call(
                    "bash",
                    {"command": f"printf same # {i}", "timeout": 5},
                    f"bash-{i}",
                )
            ]
        )
        for i in range(7)
    ]
    agent = agent_with(responses, [BashTool()])
    conversation = Conversation(agent=agent, sandbox=sandbox, max_iterations=7)

    conversation.send_message("repeat by result")
    conversation.run()

    assert conversation.status != Status.STUCK


def test_invalid_tool_json_is_observed_without_execution(sandbox):
    agent = agent_with(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="bad-json",
                        name="bash",
                        arguments={},
                        raw_arguments='{"command": ',
                        parse_error="Expecting value at line 1 column 13",
                    )
                ]
            ),
            LLMResponse(tool_calls=[call("finish", {"message": "done"}, "finish")]),
        ],
        [BashTool(), FinishTool()],
    )
    conversation = Conversation(agent=agent, sandbox=sandbox, max_iterations=2)

    conversation.send_message("run malformed tool")
    conversation.run()

    assert conversation.status == Status.FINISHED
    assert any(
        isinstance(event, ObservationEvent)
        and event.tool_call_id == "bad-json"
        and event.error
        and "Invalid JSON arguments for bash" in event.content
        and "Expecting value" in event.content
        for event in conversation.events
    )
    messages = agent._build_messages(conversation, sandbox)
    tool_calls = [
        tool_call
        for message in messages
        for tool_call in message.get("tool_calls", [])
        if tool_call["id"] == "bad-json"
    ]
    assert tool_calls[0]["function"]["arguments"] == '{"command": '


def test_llm_usage_event_recorded_for_agent_step(sandbox):
    agent = agent_with(
        [
            LLMResponse(
                tool_calls=[call("finish", {"message": "done"}, "finish")],
                usage=TokenUsage(
                    prompt_tokens=10,
                    completion_tokens=3,
                    total_tokens=13,
                ),
                cost=0.001,
            )
        ],
        [FinishTool()],
    )
    conversation = Conversation(agent=agent, sandbox=sandbox)

    conversation.send_message("finish")
    conversation.run()

    usage_events = [
        event for event in conversation.events if isinstance(event, LLMUsageEvent)
    ]
    assert len(usage_events) == 1
    assert usage_events[0].phase == "step"
    assert usage_events[0].total_tokens == 13
    assert usage_events[0].cost_usd == 0.001


def test_condensation_summary_replaces_old_events_in_messages(sandbox):
    responses = [LLMResponse(text="summary of old work")]
    agent = agent_with(responses, [FinishTool()], tokens=99_999)
    conversation = Conversation(agent=agent, sandbox=sandbox)
    for index in range(12):
        conversation.add_event(MessageEvent(role="user", text=f"old user {index}"))
    conversation.add_event(MessageEvent(role="user", text="current task"))

    agent._maybe_condense(conversation, sandbox)
    messages = agent._build_messages(conversation, sandbox)

    assert any(isinstance(event, CondensationEvent) for event in conversation.events)
    content = "\n".join(str(message.get("content") or "") for message in messages)
    assert "summary of old work" in content
    assert "current task" in content
    assert "old user 0" not in content


def test_condensation_summary_preserves_failure_evidence(sandbox):
    responses = [LLMResponse(text="summary of old work")]
    agent = agent_with(responses, [FinishTool()], tokens=99_999)
    conversation = Conversation(agent=agent, sandbox=sandbox)
    for index in range(11):
        conversation.add_event(MessageEvent(role="user", text=f"old user {index}"))
    conversation.add_event(ErrorEvent(message="stopped: repeated empty result"))
    conversation.add_event(MessageEvent(role="user", text="current task"))

    agent._maybe_condense(conversation, sandbox)
    messages = agent._build_messages(conversation, sandbox)

    content = "\n".join(str(message.get("content") or "") for message in messages)
    assert "summary of old work" in content
    assert "Failure/error evidence to preserve" in content
    assert "stopped: repeated empty result" in content


def test_implementing_plan_system_prompt_does_not_repeat_full_plan(sandbox):
    agent = agent_with([], [FinishTool()])
    conversation = Conversation(agent=agent, sandbox=sandbox)
    conversation.implementing_plan = True
    conversation.plan = Plan(
        title="Test plan",
        steps=[
            PlanStep(
                title="Edit the target file",
                files=["target.py"],
                description="This full step text should live in conversation history.",
            )
        ],
    )

    system = agent._build_messages(conversation, sandbox)[0]["content"]

    assert "Approved plan implementation" in system
    assert "Edit the target file" not in system
    assert "target.py" not in system


def test_verification_gate_rejects_finish_after_unverified_edit(sandbox):
    agent = agent_with(
        [
            LLMResponse(
                tool_calls=[
                    call(
                        "file_edit",
                        {"command": "create", "path": "x.py", "content": "x = 1\n"},
                        "edit",
                    )
                ]
            ),
            LLMResponse(tool_calls=[call("finish", {"message": "done"}, "finish-1")]),
            LLMResponse(
                tool_calls=[
                    call(
                        "finish",
                        {
                            "message": "Could not run verification because no test command is available."
                        },
                        "finish-2",
                    )
                ]
            ),
        ],
        [FileEditTool(), FinishTool()],
        policy=StaticPolicy(
            finish={
                "Could not run verification because no test command is available.": CommandPolicy(
                    risk="safe",
                    read_only=True,
                    verification_unavailable=True,
                    reason="test unavailable verification",
                )
            }
        ),
    )
    conversation = Conversation(agent=agent, sandbox=sandbox, max_iterations=3)

    conversation.send_message("add code")
    conversation.run()

    assert conversation.status == Status.FINISHED
    assert any(
        isinstance(event, ObservationEvent)
        and event.tool_name == "finish"
        and event.error
        and "Verification required" in event.content
        for event in conversation.events
    )


def test_verification_command_allows_finish_after_edit(sandbox):
    agent = agent_with(
        [
            LLMResponse(
                tool_calls=[
                    call(
                        "file_edit",
                        {"command": "create", "path": "x.py", "content": "x = 1\n"},
                        "edit",
                    )
                ]
            ),
            LLMResponse(
                tool_calls=[
                    call(
                        "bash",
                        {"command": "python -m compileall x.py", "timeout": 30},
                        "verify",
                    )
                ]
            ),
            LLMResponse(tool_calls=[call("finish", {"message": "done"}, "finish")]),
        ],
        [FileEditTool(), BashTool(), FinishTool()],
        policy=StaticPolicy(
            bash={
                "python -m compileall x.py": CommandPolicy(
                    risk="safe",
                    read_only=True,
                    is_verification=True,
                    reason="test verification command",
                )
            }
        ),
    )
    conversation = Conversation(agent=agent, sandbox=sandbox, max_iterations=3)

    conversation.send_message("add code")
    conversation.run()

    assert conversation.status == Status.FINISHED


def test_parallel_read_observations_keep_tool_call_order(sandbox):
    sandbox.write_file("a.txt", "A")
    sandbox.write_file("b.txt", "B")
    agent = agent_with(
        [
            LLMResponse(
                tool_calls=[
                    call("file_edit", {"command": "view", "path": "a.txt"}, "first"),
                    call("file_edit", {"command": "view", "path": "b.txt"}, "second"),
                    call("finish", {"message": "done"}, "finish"),
                ]
            )
        ],
        [FileEditTool(), FinishTool()],
    )
    conversation = Conversation(agent=agent, sandbox=sandbox, max_iterations=2)

    conversation.send_message("read files")
    conversation.run()

    observations = [
        event
        for event in conversation.events
        if isinstance(event, ObservationEvent) and event.tool_name == "file_edit"
    ]
    assert [event.tool_call_id for event in observations] == ["first", "second"]
    assert [event.content for event in observations] == ["A", "B"]


def test_task_routing_injects_review_directive(sandbox):
    agent = agent_with([], [FinishTool()], route=TaskRoute.REVIEW)
    conversation = Conversation(agent=agent, sandbox=sandbox)

    conversation.send_message("please review this code")
    messages = agent._build_messages(conversation, sandbox)

    assert conversation.route == TaskRoute.REVIEW
    assert "Review route" in messages[0]["content"]


def test_read_only_worker_file_tool_rejects_mutation(sandbox):
    tool = ReadOnlyFileEditTool()

    observation = tool.execute(
        FileEditAction(command="create", path="x.txt", content="nope"),
        sandbox,
    )

    assert observation.error
    assert sandbox.list_files(".") == []


def test_fanout_tool_runs_read_only_workers(sandbox):
    llm = ScriptedLLM(
        [
            LLMResponse(
                tool_calls=[call("finish", {"message": "worker one facts"}, "w1")]
            ),
            LLMResponse(
                tool_calls=[call("finish", {"message": "worker two facts"}, "w2")]
            ),
        ]
    )
    tool = FanoutTool(llm=llm, policy=StaticPolicy())  # type: ignore[arg-type]

    observation = tool.execute(
        FanoutAction(
            tasks=[
                FanoutTask(title="One", prompt="Inspect one thing"),
                FanoutTask(title="Two", prompt="Inspect another thing"),
            ]
        ),
        sandbox,
    )

    assert not observation.error
    assert {result.summary for result in observation.results} == {
        "worker one facts",
        "worker two facts",
    }


def test_fanout_emits_worker_progress_events(sandbox):
    from miniagent.events import FanoutWorkerEvent

    llm = ScriptedLLM(
        [
            LLMResponse(
                tool_calls=[call("finish", {"message": "worker facts"}, "w1")]
            ),
        ]
    )
    agent = agent_with([], [FinishTool()])
    parent = Conversation(agent=agent, sandbox=sandbox)
    tool = FanoutTool(llm=llm, policy=StaticPolicy())  # type: ignore[arg-type]

    tool.execute(
        FanoutAction(
            tasks=[FanoutTask(title="Inspect", prompt="Inspect one thing")]
        ),
        sandbox,
        conversation=parent,
        tool_call_id="fanout-parent",
    )

    worker_events = [
        event
        for event in parent.events
        if isinstance(event, FanoutWorkerEvent)
    ]
    assert worker_events
    assert worker_events[0].parent_tool_call_id == "fanout-parent"
    assert worker_events[0].title == "Inspect"
    assert worker_events[-1].status == "done"
