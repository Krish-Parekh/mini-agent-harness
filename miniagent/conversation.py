from __future__ import annotations

import enum
import threading
import uuid
from typing import TYPE_CHECKING, Callable

from miniagent.confirm import ConfirmPolicy
from miniagent.events import (
    ActionEvent,
    Attachment,
    ErrorEvent,
    Event,
    MemoryIndexEvent,
    MessageEvent,
    ObservationEvent,
    RepoInstructionsEvent,
    RewindEvent,
    WorkspaceSketchEvent,
)
from miniagent.failures import classify, redact
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


DOC_SUFFIXES = (".md", ".mdx", ".markdown", ".txt", ".rst", ".adoc")
_ENVIRONMENT_EVENTS = (RepoInstructionsEvent, WorkspaceSketchEvent, MemoryIndexEvent)


def _is_doc(path: str) -> bool:
    return path.lower().endswith(DOC_SUFFIXES)


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
        parent: Conversation | None = None,
        read_only: bool = False,
    ) -> None:
        self.id = id or _new_id()
        self.parent = parent
        self.read_only = read_only
        self.agent = agent
        self.sandbox = sandbox
        self.on_event = on_event or (lambda event: None)
        self.max_iterations = max_iterations
        self.confirm_policy = confirm_policy or ConfirmPolicy()
        self.events: list[Event] = []
        self._events_lock = threading.Lock()
        self.status = Status.IDLE
        # Set from another thread to ask the run loop to stop cooperatively; the
        # loop checks it between iterations. Cleared at the start of each run().
        self.cancel_event = threading.Event()
        self._steering: list[MessageEvent] = []
        self._steering_lock = threading.Lock()
        # When set, the agent plans (read-only) and pauses via `present_plan`
        # instead of implementing. Sticky: it stays on across clarifying
        # `ask_user` rounds and plan refinements, and only clears when the
        # user approves the plan, so the whole planning conversation,
        # including feedback after a presented plan, runs in plan mode.
        self.plan_mode = False
        self.plan: Plan | None = None
        self.implementing_plan = False
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
        client_event_id: str | None = None,
        attachments: list[Attachment] | None = None,
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
        self.add_event(
            MessageEvent(
                role="user",
                text=text,
                client_event_id=client_event_id,
                attachments=attachments or [],
            )
        )

    def steer(
        self,
        text: str,
        client_event_id: str | None = None,
        attachments: list[Attachment] | None = None,
    ) -> None:
        with self._steering_lock:
            self._steering.append(
                MessageEvent(
                    role="user",
                    text=text,
                    client_event_id=client_event_id,
                    attachments=attachments or [],
                )
            )

    def has_steering(self) -> bool:
        with self._steering_lock:
            return bool(self._steering)

    def _take_steering(self) -> None:
        with self._steering_lock:
            pending, self._steering = self._steering, []
        for message in pending:
            self.add_event(message)

    def add_event(self, event: Event) -> None:
        with self._events_lock:
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
        live = self.live_events()
        observed = {e.tool_call_id for e in live if isinstance(e, ObservationEvent)}
        return [
            event
            for event in live
            if isinstance(event, ActionEvent) and event.tool_call_id not in observed
        ]

    def live_events(self) -> list[Event]:
        hidden = {
            event_id
            for event in self.events
            if isinstance(event, RewindEvent)
            for event_id in event.hidden_event_ids
        }
        if not hidden:
            return self.events
        return [event for event in self.events if event.id not in hidden]

    def rewind(self, message_id: str) -> None:
        live = self.live_events()
        start = next(i for i, e in enumerate(live) if e.id == message_id)
        self.add_event(
            RewindEvent(
                hidden_event_ids=[
                    event.id
                    for event in live[start:]
                    if not isinstance(event, _ENVIRONMENT_EVENTS)
                ]
            )
        )
        self.status = Status.IDLE

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

        live = self.live_events()
        replaced = {e.id for e in self.events} - {e.id for e in live}
        for event in live:
            if isinstance(event, CondensationEvent):
                replaced.update(event.replaced_event_ids)
        return replaced

    def elided_event_ids(self) -> set[str]:
        from miniagent.events import CondensationEvent

        elided: set[str] = set()
        for event in self.live_events():
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
                and not _is_doc(action.arguments.get("path", ""))
            ):
                dirty = True
        return dirty

    def _observed_actions(self) -> list[tuple[ActionEvent, ObservationEvent]]:
        live = self.live_events()
        actions = {
            event.tool_call_id: event
            for event in live
            if isinstance(event, ActionEvent)
        }
        pairs: list[tuple[ActionEvent, ObservationEvent]] = []
        for event in live:
            if not isinstance(event, ObservationEvent):
                continue
            action = actions.get(event.tool_call_id)
            if action is not None:
                pairs.append((action, event))
        return pairs

    def _last_user_index(self) -> int | None:
        live = {event.id for event in self.live_events()}
        for index in range(len(self.events) - 1, -1, -1):
            event = self.events[index]
            if isinstance(event, MessageEvent) and event.role == "user" and event.id in live:
                return index
        return None

    def awaits(self, tool_call_id: str) -> bool:
        pending = self.pending_action()
        return (
            self.status == Status.WAITING_FOR_CONFIRMATION
            and pending is not None
            and pending.tool_call_id == tool_call_id
        )

    def approve(self, tool_call_id: str) -> None:
        if self.awaits(tool_call_id):
            self.run()

    def reject(self, tool_call_id: str, reason: str = "Action rejected by the user.") -> None:
        if not self.awaits(tool_call_id):
            return
        self.add_event(
            ObservationEvent(
                tool_name=self.pending_action().tool_name,
                tool_call_id=tool_call_id,
                content=reason,
                error=True,
            )
        )
        self.run()

    def request_cancel(self) -> None:
        """Ask the in-flight run loop, and every child conversation it spawned,
        to stop after its current step."""
        self.cancel_event.set()
        with self._steering_lock:
            self._steering.clear()

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set() or (
            self.parent is not None and self.parent.cancelled
        )

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
            if self.cancelled:
                self.status = Status.IDLE
                return
            self._take_steering()
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
                self.add_event(
                    ErrorEvent(
                        message=f"agent step failed: {redact(str(exc))}",
                        failure=classify(exc),
                    )
                )
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
