from __future__ import annotations

from typing import Any

from pydantic import ConfigDict

from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool

NAME_PREFIX = "mcp__"
MAX_TOOLS = 40


class McpAction(Action):
    model_config = ConfigDict(frozen=True, extra="allow")


class McpObservation(Observation):
    content: str

    def to_llm_text(self) -> str:
        return self.content


def tool_name(connection: str, tool: str) -> str:
    safe_connection = _slug(connection)
    return f"{NAME_PREFIX}{safe_connection}__{tool}"


def _slug(value: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in value.strip())


class McpTool(Tool):
    action_type = McpAction
    observation_type = McpObservation

    def __init__(
        self,
        *,
        connection: str,
        remote_name: str,
        description: str,
        input_schema: dict[str, Any],
        invoke,
        read_only: bool = False,
    ) -> None:
        self.name = tool_name(connection, remote_name)
        self.description = description or f"{remote_name} (via {connection})"
        self.parameters_schema = _normalise(input_schema)
        self.connection = connection
        self.remote_name = remote_name
        self.read_only = read_only
        self._invoke = invoke

    def execute(self, action: Action, sandbox: Sandbox) -> Observation:
        arguments = action.model_dump(exclude_none=True)
        return McpObservation(content=self._invoke(self.remote_name, arguments))


def _normalise(schema: dict[str, Any]) -> dict[str, Any]:
    if not schema:
        return {"type": "object", "properties": {}}
    normalised = dict(schema)
    normalised.setdefault("type", "object")
    normalised.setdefault("properties", {})
    return normalised
