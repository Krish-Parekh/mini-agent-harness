from __future__ import annotations

from datetime import datetime, timezone

from harbor.models.trajectories import (
    Agent,
    FinalMetrics,
    Metrics,
    Observation,
    ObservationResult,
    Step,
    ToolCall,
    Trajectory,
)

from miniagent.events import ActionEvent, Event, LLMUsageEvent, MessageEvent, ObservationEvent


def to_trajectory(
    events: list[Event], *, session_id: str, agent: Agent, final_metrics: FinalMetrics
) -> Trajectory:
    steps: list[Step] = []
    turn: Step | None = None
    turn_of_call: dict[str, Step] = {}

    def add(event: Event, **fields) -> Step:
        timestamp = datetime.fromtimestamp(event.timestamp, timezone.utc).isoformat()
        step = Step(step_id=len(steps) + 1, timestamp=timestamp, **fields)
        steps.append(step)
        return step

    for event in events:
        if isinstance(event, LLMUsageEvent):
            turn = add(
                event,
                source="agent",
                model_name=event.model,
                message="",
                tool_calls=[],
                observation=Observation(results=[]),
                metrics=Metrics(
                    prompt_tokens=event.prompt_tokens,
                    completion_tokens=event.completion_tokens,
                    cached_tokens=event.cached_prompt_tokens,
                    cost_usd=event.cost_usd,
                ),
                extra={"phase": event.phase},
            )
        elif isinstance(event, ObservationEvent):
            turn_of_call[event.tool_call_id].observation.results.append(
                ObservationResult(source_call_id=event.tool_call_id, content=event.content)
            )
        elif isinstance(event, ActionEvent) or (
            isinstance(event, MessageEvent) and event.role == "assistant"
        ):
            if turn is None:
                turn = add(
                    event, source="agent", message="", tool_calls=[], observation=Observation(results=[])
                )
            if isinstance(event, ActionEvent):
                turn.tool_calls.append(
                    ToolCall(
                        tool_call_id=event.tool_call_id,
                        function_name=event.tool_name,
                        arguments=event.arguments,
                    )
                )
                turn_of_call[event.tool_call_id] = turn
            else:
                turn.message = event.text
        elif (message := event.to_chat_message()) is not None:
            source = "user" if isinstance(event, MessageEvent) else "system"
            add(event, source=source, message=message["content"])
            turn = None

    for step in steps:
        if step.source == "agent":
            step.tool_calls = step.tool_calls or None
            step.observation = step.observation if step.observation.results else None
    return Trajectory(
        session_id=session_id, agent=agent, steps=steps, final_metrics=final_metrics
    )
