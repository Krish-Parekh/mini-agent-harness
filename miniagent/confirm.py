from __future__ import annotations

from typing import Literal

from miniagent.events import ActionEvent

ConfirmMode = Literal["never", "always", "risky"]

def blocked_in_plan_mode(action_event: ActionEvent) -> bool:
    """Read-only enforcement while planning: block workspace mutations at the
    tool layer instead of trusting the prompt."""
    if action_event.tool_name == "file_edit":
        return action_event.arguments.get("command") in ("create", "str_replace")
    if action_event.tool_name == "bash":
        # Without a model-backed policy decision, fail closed for bash in plan mode.
        return True
    return False


class ConfirmPolicy:
    def __init__(self, mode: ConfirmMode = "risky") -> None:
        self.mode = mode

    def needs_confirmation(self, action_event: ActionEvent) -> bool:
        if self.mode == "never":
            return False
        if self.mode == "always":
            return True
        return self._is_risky(action_event)

    def _is_risky(self, action_event: ActionEvent) -> bool:
        if action_event.tool_name == "file_edit":
            path = action_event.arguments.get("path", "")
            return path.startswith("/") or ".." in path
        return False
