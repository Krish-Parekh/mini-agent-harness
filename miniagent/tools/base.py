from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation

if TYPE_CHECKING:
    from miniagent.conversation import Conversation


@dataclass(frozen=True)
class ToolContext:
    conversation: Conversation
    tool_call_id: str


class Tool(ABC):
    name: str
    description: str
    action_type: type[Action]
    observation_type: type[Observation]
    parameters_schema: dict[str, Any] | None = None

    @abstractmethod
    def execute(
        self, action: Action, sandbox: Sandbox, context: ToolContext
    ) -> Observation: ...


def to_openai_schema(tool: Tool) -> dict[str, Any]:
    parameters = tool.parameters_schema
    if parameters is None:
        parameters = tool.action_type.model_json_schema()

    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": parameters,
        },
    }


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def __getitem__(self, name: str) -> Tool:
        return self._tools[name]

    def __contains__(self, name: str) -> bool:
        return name in self._tools
