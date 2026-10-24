from __future__ import annotations

from typing import Literal

from miniagent.events import ActionEvent
from miniagent.tools.mcp import NAME_PREFIX as MCP_PREFIX

PermissionMode = Literal["ask", "auto", "full"]


class ConfirmPolicy:
    def __init__(self, mode: PermissionMode = "auto") -> None:
        self.mode = mode

    def needs_confirmation(self, action_event: ActionEvent) -> bool:
        if self.mode == "full":
            return False
        return self._is_risky(action_event)

    def _is_risky(self, action_event: ActionEvent) -> bool:
        if action_event.tool_name.startswith(MCP_PREFIX):
            return True
        if action_event.tool_name == "file_edit":
            path = action_event.arguments.get("path", "")
            return path.startswith("/") or ".." in path
        return False
