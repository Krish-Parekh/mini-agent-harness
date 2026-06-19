"""Detect when the agent is stuck in repetitive or unproductive patterns.

Adapted from OpenHands' StuckDetector: analyze recent conversation events for
loops instead of aborting on result fingerprints or identical calls alone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from miniagent.events import (
    ActionEvent,
    CondensationEvent,
    Event,
    MessageEvent,
    ObservationEvent,
)

if TYPE_CHECKING:
    from miniagent.conversation import Conversation

# Large enough for alternating patterns plus a buffer for user messages.
MAX_EVENTS_TO_SCAN = 20


@dataclass(frozen=True)
class StuckDetectionThresholds:
    action_observation: int = 4
    action_error: int = 3
    monologue: int = 3
    alternating_pattern: int = 6


class StuckDetector:
    """Detects stuck patterns in a conversation's recent event history."""

    def __init__(
        self,
        conversation: Conversation,
        thresholds: StuckDetectionThresholds | None = None,
    ) -> None:
        self._conversation = conversation
        self.thresholds = thresholds or StuckDetectionThresholds()

    def reason(self) -> str | None:
        """Return a human-readable stuck reason, or None if not stuck."""
        events = self._events_since_last_user()
        if not events:
            return None

        min_threshold = min(
            self.thresholds.action_observation,
            self.thresholds.action_error,
            self.thresholds.monologue,
        )
        if len(events) < min_threshold:
            return None

        max_needed = max(
            self.thresholds.action_observation, self.thresholds.action_error
        )
        last_actions: list[Event] = []
        last_observations: list[Event] = []

        for event in reversed(events):
            if isinstance(event, ActionEvent) and len(last_actions) < max_needed:
                last_actions.append(event)
            elif isinstance(event, ObservationEvent) and len(last_observations) < max_needed:
                last_observations.append(event)
            if len(last_actions) >= max_needed and len(last_observations) >= max_needed:
                break

        if reason := self._repeating_action_observation(last_actions, last_observations):
            return reason
        if reason := self._repeating_action_error(last_actions, last_observations):
            return reason
        if reason := self._monologue(events):
            return reason
        if len(events) >= self.thresholds.alternating_pattern:
            if reason := self._alternating_action_observation(events):
                return reason
        return None

    def is_stuck(self) -> bool:
        return self.reason() is not None

    def _events_since_last_user(self) -> list[Event]:
        events = list(self._conversation.events[-MAX_EVENTS_TO_SCAN:])
        last_user = next(
            (
                i
                for i in reversed(range(len(events)))
                if isinstance(events[i], MessageEvent) and events[i].role == "user"
            ),
            -1,
        )
        if last_user != -1:
            events = events[last_user + 1 :]
        return events

    def _repeating_action_observation(
        self, last_actions: list[Event], last_observations: list[Event]
    ) -> str | None:
        threshold = self.thresholds.action_observation
        if len(last_actions) < threshold or len(last_observations) < threshold:
            return None
        if all(
            _action_eq(last_actions[0], action) for action in last_actions[:threshold]
        ) and all(
            _observation_eq(last_observations[0], observation)
            for observation in last_observations[:threshold]
        ):
            tool = getattr(last_actions[0], "tool_name", "tool")
            return (
                f"repeated the same {tool} call and result "
                f"{threshold}+ times without progress"
            )
        return None

    def _repeating_action_error(
        self, last_actions: list[Event], last_observations: list[Event]
    ) -> str | None:
        threshold = self.thresholds.action_error
        if len(last_actions) < threshold or len(last_observations) < threshold:
            return None
        if not all(
            _action_eq(last_actions[0], action) for action in last_actions[:threshold]
        ):
            return None
        if all(
            isinstance(obs, ObservationEvent) and obs.error
            for obs in last_observations[:threshold]
        ):
            tool = getattr(last_actions[0], "tool_name", "tool")
            return (
                f"repeated the same {tool} call with errors "
                f"{threshold}+ times without progress"
            )
        return None

    def _monologue(self, events: list[Event]) -> str | None:
        threshold = self.thresholds.monologue
        if len(events) < threshold:
            return None

        agent_message_count = 0
        for event in reversed(events):
            if isinstance(event, MessageEvent):
                if event.role == "assistant":
                    agent_message_count += 1
                elif event.role == "user":
                    break
            elif isinstance(event, CondensationEvent):
                continue
            else:
                break

        if agent_message_count >= threshold:
            return (
                f"sent {agent_message_count} assistant messages in a row "
                "without using a tool or receiving user input"
            )
        return None

    def _alternating_action_observation(self, events: list[Event]) -> str | None:
        threshold = self.thresholds.alternating_pattern
        last_actions: list[Event] = []
        last_observations: list[Event] = []

        for event in reversed(events):
            if isinstance(event, ActionEvent) and len(last_actions) < threshold:
                last_actions.append(event)
            elif isinstance(event, ObservationEvent) and len(last_observations) < threshold:
                last_observations.append(event)
            if len(last_actions) == threshold and len(last_observations) == threshold:
                break

        if len(last_actions) != threshold or len(last_observations) != threshold:
            return None

        actions_equal = all(
            _action_eq(last_actions[i], last_actions[i + 2])
            for i in range(threshold - 2)
        )
        observations_equal = all(
            _observation_eq(last_observations[i], last_observations[i + 2])
            for i in range(threshold - 2)
        )
        if actions_equal and observations_equal:
            return "tool calls and results are oscillating without progress"
        return None


def _action_eq(left: Event, right: Event) -> bool:
    if not isinstance(left, ActionEvent) or not isinstance(right, ActionEvent):
        return False
    return (
        left.tool_name == right.tool_name
        and json.dumps(left.arguments, sort_keys=True)
        == json.dumps(right.arguments, sort_keys=True)
        and left.parse_error == right.parse_error
    )


def _observation_eq(left: Event, right: Event) -> bool:
    if not isinstance(left, ObservationEvent) or not isinstance(right, ObservationEvent):
        return False
    return (
        left.tool_name == right.tool_name
        and left.error == right.error
        and _normalize_observation_content(left.content)
        == _normalize_observation_content(right.content)
    )


def _normalize_observation_content(content: str) -> str:
    """Strip agent-injected loop nudges before comparing observations."""
    marker = "\n\n[note] "
    if marker in content:
        return content.split(marker, 1)[0]
    return content
