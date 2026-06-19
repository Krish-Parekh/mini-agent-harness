from __future__ import annotations

import json
import time
import uuid
from typing import Annotated, Any, Literal, Union, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

Source: TypeAlias = Literal["user", "agent", "environment"]


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


class Event(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=_new_id)
    timestamp: float = Field(default_factory=time.time)
    source: Source
    kind: str

    def to_chat_message(self) -> dict | None:
        return None


class MessageEvent(Event):
    kind: Literal["message"] = "message"
    source: Source = "user"
    role: Literal["user", "assistant", "system"]
    text: str

    def to_chat_message(self) -> dict:
        return {"role": self.role, "content": self.text}


class ActionEvent(Event):
    kind: Literal["action"] = "action"
    source: Source = "agent"
    tool_name: str
    arguments: dict[str, Any]
    tool_call_id: str
    raw_arguments: str | None = None
    parse_error: str | None = None

    def to_chat_message(self) -> dict:
        arguments = self.raw_arguments
        if arguments is None:
            arguments = json.dumps(self.arguments)
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": self.tool_call_id,
                    "type": "function",
                    "function": {
                        "name": self.tool_name,
                        "arguments": arguments,
                    },
                }
            ],
        }


class ObservationEvent(Event):
    kind: Literal["observation"] = "observation"
    source: Source = "environment"
    tool_name: str
    tool_call_id: str
    content: str
    error: bool = False
    # Wall-clock the tool took to run, when the tool measures it (e.g. bash).
    # Surfaced structurally so the UI can show timing without parsing `content`.
    duration_ms: int | None = None
    # Structured payload for the UI (endpoints, result URLs, etc.).
    details: dict[str, Any] | None = None

    def to_chat_message(self) -> dict:
        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "content": self.content,
        }


class CondensationEvent(Event):
    kind: Literal["condensation"] = "condensation"
    source: Source = "agent"
    summary: str
    replaced_event_ids: list[str]

    def to_chat_message(self) -> dict:
        return {"role": "user", "content": f"[conversation summary]\n{self.summary}"}


class LLMUsageEvent(Event):
    kind: Literal["llm_usage"] = "llm_usage"
    source: Source = "agent"
    phase: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class FanoutWorkerEvent(Event):
    kind: Literal["fanout_worker"] = "fanout_worker"
    source: Source = "agent"
    parent_tool_call_id: str
    worker_index: int
    title: str
    status: Literal["running", "done", "error"]
    activity: str | None = None


class ErrorEvent(Event):
    kind: Literal["error"] = "error"
    source: Source = "environment"
    message: str

    def to_chat_message(self) -> dict:
        # User role: mid-history system messages are inconsistently honored,
        # and the prefix keeps it unambiguous in the transcript.
        return {"role": "user", "content": f"[error] {self.message}"}


Events: TypeAlias = Annotated[
    Union[
        MessageEvent,
        ActionEvent,
        ObservationEvent,
        CondensationEvent,
        LLMUsageEvent,
        FanoutWorkerEvent,
        ErrorEvent,
    ],
    Field(discriminator="kind"),
]
