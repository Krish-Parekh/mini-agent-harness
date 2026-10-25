from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from miniagent.agent import Agent
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation, Status
from miniagent.events import (
    Event,
    MessageEvent,
    ObservationEvent,
    WorkerEvent,
    WorkerResultEvent,
    WorkerState,
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
        parent = context.conversation
        self.conversation = Conversation(
            agent=agent,
            sandbox=sandbox,
            on_event=self._relay,
            max_iterations=max_iterations,
            confirm_policy=ConfirmPolicy(parent.confirm_policy.mode),
            id=f"{parent.id}-w-{state.worker_id}",
            parent=parent,
            read_only=read_only,
            directive=directive,
            refuse_confirmations=True,
        )
        self.conversation.plan_mode = parent.plan_mode
        self.conversation.events = list(history)
        self.on_end: Callable[[Worker], dict[str, Any]] = lambda worker: {}
        self.on_deliver: Callable[[Worker], dict[str, Any]] = lambda worker: {}

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

    def run(self, prompt: str) -> None:
        conversation = self.conversation
        conversation.send_message(prompt)
        try:
            conversation.run()
        finally:
            conversation.agent.close()
        outcome = self._outcome()
        try:
            outcome |= self.on_end(self)
        except Exception as exc:
            note = f"MiniAgent could not save this worker's changes: {exc}"
            outcome |= {
                "status": "failed",
                "stop_reason": "error",
                "report": f"{outcome['report']}\n\n{note}" if outcome["report"] else note,
            }
        self.publish(**outcome)

    def deliver(self) -> WorkerResultEvent:
        if update := self.on_deliver(self):
            self.publish(**update)
        return WorkerResultEvent(**self.state.model_dump())

    def _outcome(self) -> dict[str, Any]:
        conversation = self.conversation
        if conversation.status == Status.FINISHED:
            return {"status": "done", "stop_reason": None, "report": self._finish_message()}
        report = self._last_reply()
        if conversation.cancelled:
            return {"status": "cancelled", "stop_reason": "cancelled", "report": report}
        if conversation.status in (Status.ERROR, Status.STUCK):
            return {"status": "failed", "stop_reason": "error", "report": report}
        reason = "step_limit" if conversation.hit_step_limit else "no_finish"
        return {"status": "partial", "stop_reason": reason, "report": report}

    def _turn(self) -> list[Event]:
        events = self.conversation.events
        start = max(
            (i for i, e in enumerate(events) if isinstance(e, MessageEvent) and e.role == "user"),
            default=0,
        )
        return events[start:]

    def _finish_message(self) -> str | None:
        return next(
            (
                event.content
                for event in reversed(self._turn())
                if isinstance(event, ObservationEvent)
                and event.tool_name == "finish"
                and not event.error
            ),
            None,
        )

    def _last_reply(self) -> str | None:
        return next(
            (
                event.text
                for event in reversed(self._turn())
                if isinstance(event, MessageEvent) and event.role == "assistant" and event.text
            ),
            None,
        )
