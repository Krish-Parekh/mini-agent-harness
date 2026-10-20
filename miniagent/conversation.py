from __future__ import annotations

import enum
import threading
import uuid
from typing import TYPE_CHECKING, Callable

from miniagent.classification import TaskRoute
from miniagent.confirm import ConfirmPolicy
from miniagent.events import (
    ActionEvent,
    ErrorEvent,
    Event,
    MessageEvent,
    ObservationEvent,
)
from miniagent.sandbox.base import SandboxError, SandboxExpired
from miniagent.stuck_detector import StuckDetectionThresholds, StuckDetector

if TYPE_CHECKING:
    from miniagent.agent import Agent
    from miniagent.policy import PolicyProvider
    from miniagent.sandbox.base import Sandbox
    from miniagent.tools.plan import Plan


class Status(str, enum.Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    FINISHED = "finished"
    ERROR = "error"
    STUCK = "stuck"


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
        stuck_detection: bool = True,
        stuck_detection_thresholds: StuckDetectionThresholds | None = None,
    ) -> None:
        self.id = id or _new_id()
        self.agent = agent
        self.sandbox = sandbox
        self.on_event = on_event or (lambda event: None)
        self.max_iterations = max_iterations
        self.confirm_policy = confirm_policy or ConfirmPolicy()
        self.events: list[Event] = []
        self.status = Status.IDLE
        # Set from another thread to ask the run loop to stop cooperatively; the
        # loop checks it between iterations. Cleared at the start of each run().
        self.cancel_event = threading.Event()
        # When set, the agent plans (read-only) and pauses via `present_plan`
        # instead of implementing. Sticky: it stays on across clarifying
        # `ask_user` rounds and plan refinements, and only clears when the
        # user approves the plan, so the whole planning conversation,
        # including feedback after a presented plan, runs in plan mode.
        self.plan_mode = False
        self.plan: Plan | None = None
        self.implementing_plan = False
        self.route = TaskRoute.DEFAULT
        if stuck_detection:
            self._stuck_detector = StuckDetector(
                self,
                thresholds=stuck_detection_thresholds or StuckDetectionThresholds(),
            )
        else:
            self._stuck_detector = None

    @property
    def stuck_detector(self) -> StuckDetector | None:
        return self._stuck_detector

    def send_message(
        self,
        text: str,
        plan_mode: bool = False,
        route: TaskRoute | None = None,
        client_event_id: str | None = None,
    ) -> None:
        # Only ever turn it on here; plan approval clears it. A plain reply
        # (answering a question, refining the plan) keeps the existing mode.
        if plan_mode:
            self.plan_mode = True
        self.close_orphaned_actions(
            "Not executed: the user sent a new message instead of approving this call."
        )
        if self.status == Status.WAITING_FOR_CONFIRMATION:
            self.status = Status.IDLE
        self.route = route or self.agent.classify_task_route(
            text, plan_mode=self.plan_mode
        )
        self.add_event(
            MessageEvent(role="user", text=text, client_event_id=client_event_id)
        )

    def add_event(self, event: Event) -> None:
        self.events.append(event)
        self.on_event(event)

    def set_finished(self) -> None:
        self.status = Status.FINISHED

    def set_idle(self) -> None:
        self.status = Status.IDLE

    def set_error(self) -> None:
        self.status = Status.ERROR

    def set_stuck(self) -> None:
        self.status = Status.STUCK

    def needs_confirmation(self, action_event: ActionEvent) -> bool:
        return self.confirm_policy.needs_confirmation(action_event)

    def set_waiting_for_confirmation(self) -> None:
        self.status = Status.WAITING_FOR_CONFIRMATION

    def pending_action(self) -> ActionEvent | None:
        pending = self.pending_actions()
        return pending[0] if pending else None

    def pending_actions(self) -> list[ActionEvent]:
        observed = {
            e.tool_call_id for e in self.events if isinstance(e, ObservationEvent)
        }
        return [
            event
            for event in self.events
            if isinstance(event, ActionEvent) and event.tool_call_id not in observed
        ]

    def close_orphaned_actions(self, reason: str) -> None:
        for action in self.pending_actions():
            self.add_event(
                ObservationEvent(
                    tool_name=action.tool_name,
                    tool_call_id=action.tool_call_id,
                    content=f"{reason} Re-issue the call if it is still needed.",
                    error=True,
                )
            )

    def compacted_event_ids(self) -> set[str]:
        from miniagent.events import CondensationEvent

        replaced: set[str] = set()
        for event in self.events:
            if isinstance(event, CondensationEvent):
                replaced.update(event.replaced_event_ids)
        return replaced

    def elided_event_ids(self) -> set[str]:
        from miniagent.events import CondensationEvent

        elided: set[str] = set()
        for event in self.events:
            if isinstance(event, CondensationEvent):
                elided.update(event.elided_event_ids)
        return elided

    def condensation_candidates(self, retain_chars: int | None = None) -> list[Event]:
        from miniagent.events import (
            CondensationEvent,
            RepoInstructionsEvent,
            WorkspaceSketchEvent,
        )

        compacted = self.compacted_event_ids()
        live = [
            event
            for event in self.events
            if event.id not in compacted and not isinstance(event, CondensationEvent)
        ]
        if retain_chars is None:
            last_user_index = self._last_user_index()
            if last_user_index is None:
                return []
            cut = live.index(self.events[last_user_index])
        else:
            cut = self._retained_cut(live, retain_chars)
        candidates = [
            event
            for event in live[:cut]
            if not isinstance(event, (RepoInstructionsEvent, WorkspaceSketchEvent))
        ]
        observed = {
            event.tool_call_id
            for event in candidates
            if isinstance(event, ObservationEvent)
        }
        if any(
            isinstance(event, ActionEvent) and event.tool_call_id not in observed
            for event in candidates
        ):
            return []
        return candidates

    @staticmethod
    def _retained_cut(live: list[Event], retain_chars: int) -> int:
        kept = 0
        cut = len(live)
        while cut > 0 and kept < retain_chars:
            cut -= 1
            kept += len(live[cut].model_dump_json())
        while cut < len(live) and isinstance(live[cut], ObservationEvent):
            cut += 1
        return cut

    def has_unverified_changes(self, policy: PolicyProvider | None = None) -> bool:
        dirty = False
        for action, observation in self._observed_actions():
            if action.tool_name == "bash":
                if policy is None:
                    continue
                command = action.arguments.get("command", "")
                command_policy = policy.classify_bash(command)
                if command_policy.is_verification:
                    dirty = False
                elif not observation.error and command_policy.mutates_workspace:
                    dirty = True
            elif (
                action.tool_name == "file_edit"
                and action.arguments.get("command") in ("create", "str_replace")
                and not observation.error
            ):
                dirty = True
        return dirty

    def _observed_actions(self) -> list[tuple[ActionEvent, ObservationEvent]]:
        actions = {
            event.tool_call_id: event
            for event in self.events
            if isinstance(event, ActionEvent)
        }
        pairs: list[tuple[ActionEvent, ObservationEvent]] = []
        for event in self.events:
            if not isinstance(event, ObservationEvent):
                continue
            action = actions.get(event.tool_call_id)
            if action is not None:
                pairs.append((action, event))
        return pairs

    def _last_user_index(self) -> int | None:
        for index in range(len(self.events) - 1, -1, -1):
            event = self.events[index]
            if isinstance(event, MessageEvent) and event.role == "user":
                return index
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

    def request_cancel(self) -> None:
        """Ask the in-flight run loop to stop after its current step."""
        self.cancel_event.set()

    def run(self) -> None:
        self.cancel_event.clear()
        if self.status != Status.WAITING_FOR_CONFIRMATION:
            self.close_orphaned_actions(
                "Not executed: the previous run stopped before this call ran."
            )
        self.status = Status.RUNNING
        for _ in range(self.max_iterations):
            # Cooperative stop: a step runs to completion (the current LLM call
            # or tool can't be interrupted), then we bail before the next one.
            if self.cancel_event.is_set():
                self.status = Status.IDLE
                return
            if self._stuck_detector is not None:
                reason = self._stuck_detector.reason()
                if reason is not None:
                    self.add_event(ErrorEvent(message=f"stuck: {reason}"))
                    self.set_stuck()
                    return
            try:
                self.agent.step(self, self.sandbox)
            except SandboxError as exc:
                code = "sandbox_expired" if isinstance(exc, SandboxExpired) else "sandbox_unavailable"
                self.close_orphaned_actions(f"Not executed: {code}.")
                self.add_event(ErrorEvent(message=f"{code}: {exc}"))
                self.status = Status.ERROR
                return
            except Exception as exc:
                self.close_orphaned_actions("Not executed: the agent step failed.")
                self.add_event(ErrorEvent(message=f"agent step failed: {exc}"))
                self.status = Status.ERROR
                return
            if self.status != Status.RUNNING:
                return
        # Exhausted the loop while still running. Give the model one final
        # no-tools chance to synthesize the work so the user isn't left with
        # only a control-plane error.
        try:
            self.agent.early_stop(self, self.sandbox)
        except Exception as exc:
            self.add_event(
                ErrorEvent(
                    message=(
                        f"reached max iterations ({self.max_iterations}) and "
                        f"early-stop synthesis failed: {exc}"
                    )
                )
            )
            self.status = Status.ERROR
