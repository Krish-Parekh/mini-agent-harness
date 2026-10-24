from __future__ import annotations

import asyncio
from types import SimpleNamespace

from backend.runtime.manager import QueuedMessage
from backend.service.conversation import ConversationService
from miniagent.agent import Agent
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation, Status
from miniagent.events import ActionEvent, MessageEvent, ObservationEvent
from miniagent.llm import LLMResponse, ToolCall
from miniagent.sandbox.local import LocalSandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool, ToolRegistry
from miniagent.tools.finish import FinishTool
from tests.test_agent_history import QueueLLM
from tests.test_sandbox_failures import SafePolicy


class ProbeAction(Action):
    pass


class ProbeObservation(Observation):
    def to_llm_text(self) -> str:
        return "probed"


class SteeringProbe(Tool):
    name = "probe"
    description = "probe"
    action_type = ProbeAction
    observation_type = ProbeObservation

    def execute(self, action, sandbox, context):
        context.conversation.steer("also update the README")
        return ProbeObservation()


def test_a_steer_message_lands_after_the_tool_result_at_the_next_step(tmp_path):
    llm = QueueLLM(
        LLMResponse(tool_calls=[ToolCall(id="call_probe", name="probe", arguments={})]),
        LLMResponse(text="done"),
    )
    conversation = Conversation(
        agent=Agent(llm=llm, tools=ToolRegistry([SteeringProbe(), FinishTool()]), policy=SafePolicy()),
        sandbox=LocalSandbox(str(tmp_path)),
        confirm_policy=ConfirmPolicy("full"),
        stuck_detection=False,
    )
    conversation.send_message("fix the bug")
    conversation.run()

    kinds = [
        (type(e).__name__, getattr(e, "text", None))
        for e in conversation.events
        if isinstance(e, (MessageEvent, ActionEvent, ObservationEvent))
    ]
    assert kinds == [
        ("MessageEvent", "fix the bug"),
        ("ActionEvent", None),
        ("ObservationEvent", None),
        ("MessageEvent", "also update the README"),
        ("MessageEvent", "done"),
    ]
    second_call = llm.seen[1]
    roles = [m["role"] for m in second_call if m["role"] != "system"]
    tool_index = roles.index("tool")
    assert roles[tool_index - 1] == "assistant"
    assert any("also update the README" in str(m["content"]) for m in second_call)


def test_stopping_drops_pending_steer_messages(tmp_path):
    conversation = Conversation(agent=SimpleNamespace(), sandbox=LocalSandbox(str(tmp_path)))
    conversation.steer("later")
    conversation.request_cancel()
    assert not conversation.has_steering()


class FakeConversation:
    def __init__(self) -> None:
        self.status = Status.RUNNING
        self.cancel_event = asyncio.Event()
        self.steered: list[str] = []
        self.sent: list[str] = []
        self.plan_mode = False
        self.confirm_policy = ConfirmPolicy()

    def steer(self, text, **kwargs) -> None:
        self.steered.append(text)

    def has_steering(self) -> bool:
        return False

    def send_message(self, text, **kwargs) -> None:
        self.sent.append(text)

    def run(self) -> None:
        pass


def _managed():
    return SimpleNamespace(
        conversation=FakeConversation(),
        lock=asyncio.Lock(),
        queue=[],
        broker=SimpleNamespace(published=[], publish=lambda item: None),
        set_model=lambda model: None,
    )


def _service():
    service = ConversationService(SimpleNamespace(), None, None)
    service.spawned = []
    service._spawn = lambda coro: (service.spawned.append(coro), coro.close())
    return service


async def test_while_running_steer_goes_to_the_loop_and_queue_waits():
    service, managed = _service(), _managed()
    await service.send_message(managed, "steer this")
    await service.send_message(managed, "after that", mode="queue")

    assert managed.conversation.steered == ["steer this"]
    assert [q.text for q in managed.queue] == ["after that"]
    assert managed.conversation.sent == []
    assert service.spawned == []


async def test_the_next_queued_message_starts_when_the_turn_ends():
    service, managed = _service(), _managed()
    managed.queue = [
        QueuedMessage(id="q1", text="one", attachments=[], model=None, client_event_id=None, plan_mode=False, permission_mode="auto"),
        QueuedMessage(id="q2", text="two", attachments=[], model=None, client_event_id=None, plan_mode=False, permission_mode="auto"),
    ]
    managed.conversation.status = Status.IDLE

    service._continue(managed)

    assert managed.conversation.sent == ["one"]
    assert [q.id for q in managed.queue] == ["q2"]
    assert len(service.spawned) == 1


async def test_a_stopped_turn_holds_the_queue_and_queued_items_can_be_removed():
    service, managed = _service(), _managed()
    managed.queue = [QueuedMessage(id="q1", text="one", attachments=[], model=None, client_event_id=None, plan_mode=False, permission_mode="auto")]
    managed.conversation.status = Status.IDLE
    managed.conversation.cancel_event.set()

    service._continue(managed)
    assert managed.conversation.sent == []

    assert service.unqueue(managed, "q1")
    assert managed.queue == []
    assert not service.unqueue(managed, "q1")
