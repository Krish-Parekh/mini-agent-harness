from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING, Callable

from miniagent.events import ErrorEvent, Event, MessageEvent

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
        id: str | None = None,
    ) -> None:
        self.id = id or _new_id()
        self.agent = agent
        self.sandbox = sandbox
        self.on_event = on_event or (lambda event: None)
        self.max_iterations = max_iterations
        self.events: list[Event] = []
        self.status = Status.IDLE

    def send_message(self, text: str) -> None:
        self.add_event(MessageEvent(role="user", text=text))

    def add_event(self, event: Event) -> None:
        self.events.append(event)
        self.on_event(event)

    def set_finished(self) -> None:
        self.status = Status.FINISHED

    def run(self) -> None:
        self.status = Status.RUNNING
        for _ in range(self.max_iterations):
            if self.status in (Status.FINISHED, Status.ERROR):
                break
            try:
                self.agent.step(self, self.sandbox)
            except Exception as exc:
                self.add_event(ErrorEvent(message=f"agent step failed: {exc}"))
                self.status = Status.ERROR
                break
            if self.status == Status.WAITING_FOR_CONFIRMATION:
                break
        else:
            # Loop exhausted its iteration budget without finishing.
            if self.status == Status.RUNNING:
                self.status = Status.IDLE
