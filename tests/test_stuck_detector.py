from __future__ import annotations

from miniagent.conversation import Conversation, Status
from miniagent.events import ActionEvent, ErrorEvent, MessageEvent, ObservationEvent
from miniagent.llm import LLMResponse
from miniagent.stuck_detector import StuckDetectionThresholds
from miniagent.tools.bash import BashTool
from miniagent.tools.finish import FinishTool
from tests.test_agent_reliability import agent_with, call


def _bash_pair(command: str, output: str, *, error: bool = False, call_id: str = "call"):
    action = ActionEvent(
        tool_name="bash",
        arguments={"command": command, "timeout": 5},
        tool_call_id=call_id,
    )
    observation = ObservationEvent(
        tool_name="bash",
        tool_call_id=call_id,
        content=output,
        error=error,
    )
    return action, observation


def test_stuck_detector_ignores_different_calls_with_same_output(sandbox):
    conversation = Conversation(
        agent=agent_with([], [BashTool()]),
        sandbox=sandbox,
        stuck_detection=True,
    )
    conversation.send_message("start")
    for index in range(3):
        action, observation = _bash_pair(
            f"printf same #{index}",
            "same",
            call_id=f"call-{index}",
        )
        conversation.add_event(action)
        conversation.add_event(observation)

    detector = conversation.stuck_detector
    assert detector is not None
    assert detector.is_stuck() is False


def test_stuck_detector_action_observation_loop(sandbox):
    conversation = Conversation(
        agent=agent_with([], [BashTool()]),
        sandbox=sandbox,
        stuck_detection=True,
    )
    conversation.send_message("start")
    for index in range(4):
        action, observation = _bash_pair("printf repeat", "repeat", call_id=f"call-{index}")
        conversation.add_event(action)
        conversation.add_event(observation)

    detector = conversation.stuck_detector
    assert detector is not None
    assert detector.is_stuck() is True
    assert "repeated the same bash call and result" in detector.reason()


def test_stuck_detector_respects_custom_threshold(sandbox):
    conversation = Conversation(
        agent=agent_with([], [BashTool()]),
        sandbox=sandbox,
        stuck_detection=True,
        stuck_detection_thresholds=StuckDetectionThresholds(action_observation=6),
    )
    conversation.send_message("start")
    for index in range(4):
        action, observation = _bash_pair("printf repeat", "repeat", call_id=f"call-{index}")
        conversation.add_event(action)
        conversation.add_event(observation)

    detector = conversation.stuck_detector
    assert detector is not None
    assert detector.is_stuck() is False


def test_stuck_detector_action_error_loop(sandbox):
    conversation = Conversation(
        agent=agent_with([], [BashTool()]),
        sandbox=sandbox,
        stuck_detection=True,
    )
    conversation.send_message("start")
    for index in range(3):
        action, observation = _bash_pair(
            "printf fail",
            "old_str not found",
            error=True,
            call_id=f"call-{index}",
        )
        conversation.add_event(action)
        conversation.add_event(observation)

    detector = conversation.stuck_detector
    assert detector is not None
    assert detector.is_stuck() is True
    assert "with errors" in detector.reason()


def test_stuck_detector_monologue(sandbox):
    conversation = Conversation(
        agent=agent_with([], [BashTool()]),
        sandbox=sandbox,
        stuck_detection=True,
    )
    conversation.send_message("start")
    for index in range(3):
        conversation.add_event(
            MessageEvent(role="assistant", text=f"thinking out loud {index}")
        )

    detector = conversation.stuck_detector
    assert detector is not None
    assert detector.is_stuck() is True
    assert "assistant messages in a row" in detector.reason()


def test_conversation_run_pauses_on_stuck(sandbox):
    responses = [
        LLMResponse(
            tool_calls=[
                call("bash", {"command": "printf repeat", "timeout": 5}, f"bash-{index}")
            ]
        )
        for index in range(6)
    ]
    conversation = Conversation(
        agent=agent_with(responses, [BashTool()]),
        sandbox=sandbox,
        max_iterations=10,
        stuck_detection=True,
        stuck_detection_thresholds=StuckDetectionThresholds(action_observation=4),
    )

    conversation.send_message("repeat")
    conversation.run()

    assert conversation.status == Status.STUCK
    assert any(
        isinstance(event, MessageEvent)
        and event.role == "user"
        for event in conversation.events
    )
    assert conversation.events[-1].kind == "error"
    assert isinstance(conversation.events[-1], ErrorEvent)
    assert "stuck:" in conversation.events[-1].message


def test_conversation_resumes_after_stuck(sandbox):
    responses = [
        LLMResponse(
            tool_calls=[
                call("bash", {"command": "printf repeat", "timeout": 5}, f"bash-{index}")
            ]
        )
        for index in range(6)
    ] + [LLMResponse(tool_calls=[call("finish", {"message": "done"}, "finish")])]
    conversation = Conversation(
        agent=agent_with(responses, [BashTool(), FinishTool()]),
        sandbox=sandbox,
        max_iterations=10,
        stuck_detection=True,
        stuck_detection_thresholds=StuckDetectionThresholds(action_observation=4),
    )

    conversation.send_message("repeat")
    conversation.run()
    assert conversation.status == Status.STUCK

    conversation.send_message("try again")
    conversation.run()
    assert conversation.status == Status.FINISHED
