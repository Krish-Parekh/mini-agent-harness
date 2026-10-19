from __future__ import annotations

import contextvars
import json
from typing import Any, Callable, TypeVar

MAX_ATTRIBUTE_CHARS = 16_000

T = TypeVar("T")


def current_trace_id() -> str | None:
    try:
        from opentelemetry import trace
    except ImportError:
        return None
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return format(context.trace_id, "032x")


def clip_attribute(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) <= MAX_ATTRIBUTE_CHARS:
        return text
    hidden = len(text) - MAX_ATTRIBUTE_CHARS
    return text[:MAX_ATTRIBUTE_CHARS] + f"… [{hidden} chars truncated]"


def usage_details(
    *, prompt: int, completion: int, cache_read: int, cache_creation: int
) -> dict[str, int]:
    return {
        "input": max(prompt - cache_read - cache_creation, 0),
        "output": completion,
        "input_cache_read": cache_read,
        "input_cache_creation": cache_creation,
        "total": prompt + completion,
    }


def generation_attributes(
    *,
    model: str,
    phase: str,
    messages: list[dict],
    output: Any,
    usage: dict[str, int],
    cost: float,
) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "langfuse.observation.type": "generation",
        "langfuse.observation.model.name": model,
        "langfuse.observation.input": clip_attribute(messages),
        "langfuse.observation.output": clip_attribute(output),
        "langfuse.observation.usage_details": json.dumps(usage),
        "langfuse.observation.metadata.phase": phase,
    }
    if cost:
        attributes["langfuse.observation.cost_details"] = json.dumps({"total": cost})
    return attributes


def tool_attributes(*, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "langfuse.observation.type": "tool",
        "gen_ai.tool.name": name,
        "langfuse.observation.input": clip_attribute(arguments),
    }


def tool_result_attributes(
    *, content: str, error: bool, details: dict[str, Any] | None
) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "langfuse.observation.output": clip_attribute(content),
        "tool.error": error,
    }
    if error:
        attributes["langfuse.observation.level"] = "ERROR"
    spill_path = (details or {}).get("spill_path")
    if spill_path:
        attributes["tool.spill_path"] = spill_path
    return attributes


def trace_attributes(
    *, session_id: str, user_id: str | None, name: str, input: str | None = None
) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "langfuse.observation.type": "agent",
        "langfuse.session.id": session_id,
        "langfuse.trace.name": name,
    }
    if user_id:
        attributes["langfuse.user.id"] = user_id
    if input:
        attributes["langfuse.trace.input"] = clip_attribute(input)
    return attributes


def bind_context(fn: Callable[..., T]) -> Callable[..., T]:
    context = contextvars.copy_context()
    return lambda *args, **kwargs: context.run(fn, *args, **kwargs)
