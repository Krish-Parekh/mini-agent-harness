from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation


class Tool(ABC):
    name: str
    description: str
    action_type: type[Action]
    observation_type: type[Observation]

    @abstractmethod
    def execute(self, action: Action, sandbox: Sandbox) -> Observation: ...


def to_openai_schema(tool: Tool) -> dict[str, Any]:

    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.action_type.model_json_schema(),
        },
    }


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def __getitem__(self, name: str) -> Tool:
        return self._tools[name]

    def __contains__(self, name: str) -> bool:
        return name in self._tools
