from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING, Callable

from miniagent.confirm import ConfirmPolicy
from miniagent.events import (
    ActionEvent,
    ErrorEvent,
    Event,
    MessageEvent,
    ObservationEvent,
)

if TYPE_CHECKING:
    from miniagent.agent import Agent
    from miniagent.sandbox.base import Sandbox


class Status(str, enum.Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    FINISHED = "finished"
    ERROR = "error"


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


class Conversation:
    def __init__(
        self,
        agent: Agent,
        sandbox: Sandbox,
        on_event: Callable[[Event], None] | None = None,
        max_iterations: int = 50,
        confirm_policy: ConfirmPolicy | None = None,
        id: str | None = None,
    ) -> None:
        self.id = id or _new_id()
        self.agent = agent
        self.sandbox = sandbox
        self.on_event = on_event or (lambda event: None)
        self.max_iterations = max_iterations
        self.confirm_policy = confirm_policy or ConfirmPolicy()
        self.events: list[Event] = []
        self.status = Status.IDLE

    def send_message(self, text: str) -> None:
        self.add_event(MessageEvent(role="user", text=text))

    def add_event(self, event: Event) -> None:
        self.events.append(event)
        self.on_event(event)

    def set_finished(self) -> None:
        self.status = Status.FINISHED

    def set_idle(self) -> None:
        self.status = Status.IDLE

    def needs_confirmation(self, action_event: ActionEvent) -> bool:
        return self.confirm_policy.needs_confirmation(action_event)

    def set_waiting_for_confirmation(self) -> None:
        self.status = Status.WAITING_FOR_CONFIRMATION

    def pending_action(self) -> ActionEvent | None:
        observed = {
            e.tool_call_id for e in self.events if isinstance(e, ObservationEvent)
        }
        for event in reversed(self.events):
            if isinstance(event, ActionEvent) and event.tool_call_id not in observed:
                return event
        return None

    def approve(self) -> None:
        if self.status == Status.WAITING_FOR_CONFIRMATION:
            self.run()

    def reject(self, reason: str = "Action rejected by the user.") -> None:
        if self.status != Status.WAITING_FOR_CONFIRMATION:
            return
        pending = self.pending_action()
        if pending is not None:
            self.add_event(
                ObservationEvent(
                    tool_name=pending.tool_name,
                    tool_call_id=pending.tool_call_id,
                    content=reason,
                    error=True,
                )
            )
        self.run()

    def run(self) -> None:
        self.status = Status.RUNNING
        for _ in range(self.max_iterations):
            try:
                self.agent.step(self, self.sandbox)
            except Exception as exc:
                self.add_event(ErrorEvent(message=f"agent step failed: {exc}"))
                self.status = Status.ERROR
                return
            if self.status != Status.RUNNING:
                return
        self.status = Status.IDLE
