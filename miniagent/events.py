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

    def to_chat_message(self) -> dict:
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": self.tool_call_id,
                    "type": "function",
                    "function": {
                        "name": self.tool_name,
                        "arguments": json.dumps(self.arguments),
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


class ErrorEvent(Event):
    kind: Literal["error"] = "error"
    source: Source = "environment"
    message: str


Events: TypeAlias = Annotated[
    Union[
        MessageEvent,
        ActionEvent,
        ObservationEvent,
        CondensationEvent,
        ErrorEvent,
    ],
    Field(discriminator="kind"),
]
