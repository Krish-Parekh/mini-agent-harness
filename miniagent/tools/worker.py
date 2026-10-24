from __future__ import annotations

from collections.abc import Sequence

from miniagent.agent import Agent
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation, Status
from miniagent.events import (
    Event,
    ObservationEvent,
    WorkerEvent,
    WorkerState,
    WorkerStatus,
    WorkerStatusEvent,
)
from miniagent.sandbox.base import Sandbox
from miniagent.tools.base import ToolContext


class Worker:
    def __init__(
        self,
        context: ToolContext,
        state: WorkerState,
        agent: Agent,
        sandbox: Sandbox,
        *,
        max_iterations: int,
        read_only: bool = False,
        directive: str | None = None,
        history: Sequence[Event] = (),
    ) -> None:
        self._context = context
        self.state = state
        self.conversation = Conversation(
            agent=agent,
            sandbox=sandbox,
            on_event=self._relay,
            max_iterations=max_iterations,
            confirm_policy=ConfirmPolicy("full"),
            id=f"{context.conversation.id}-w-{state.worker_id}",
            parent=context.conversation,
            read_only=read_only,
            directive=directive,
        )
        self.conversation.events = list(history)

    def _relay(self, event: Event) -> None:
        self._context.conversation.add_event(
            WorkerEvent(
                parent_tool_call_id=self._context.tool_call_id,
                worker_id=self.state.worker_id,
                event=event,
            )
        )

    def publish(self, **update) -> None:
        self.state = self.state.model_copy(update=update)
        self._context.conversation.add_event(
            WorkerStatusEvent(
                parent_tool_call_id=self._context.tool_call_id,
                **self.state.model_dump(),
            )
        )

    def run(self, prompt: str) -> tuple[WorkerStatus, str | None]:
        conversation = self.conversation
        conversation.send_message(prompt)
        conversation.run()
        if conversation.status == Status.FINISHED:
            return "done", self._finish_message()
        return ("cancelled" if conversation.cancelled else "failed"), None

    def _finish_message(self) -> str:
        return next(
            event.content
            for event in reversed(self.conversation.events)
            if isinstance(event, ObservationEvent)
            and event.tool_name == "finish"
            and not event.error
        )
