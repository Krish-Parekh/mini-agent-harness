from __future__ import annotations

import re
from typing import Literal

from miniagent.events import ActionEvent

ConfirmMode = Literal["never", "always", "risky"]

RISKY_PATTERNS = [
    r"\brm\s+-\S*[rf]",                  # rm -rf / -r / -f
    r"\bmkfs\b",                         # format a filesystem
    r"\bdd\b",                           # raw disk write
    r"git\s+push\b.*(--force|-f)\b",     # force push
    r"git\s+reset\s+--hard\b",           # discard changes
    r"\b(shutdown|reboot|halt)\b",
    r"curl\b[^|]*\|\s*(sudo\s+)?(ba)?sh",  # curl ... | sh
    r"wget\b[^|]*\|\s*(sudo\s+)?(ba)?sh",  # wget ... | sh
    r">\s*/dev/(sd|nvme|disk)",          # overwrite a block device
    r":\(\)\s*\{\s*:\|:&\s*\};:",        # fork bomb
]


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
        if action_event.tool_name == "bash":
            command = action_event.arguments.get("command", "")
            return any(re.search(p, command, re.IGNORECASE) for p in RISKY_PATTERNS)
        if action_event.tool_name == "file_edit":
            path = action_event.arguments.get("path", "")
            return path.startswith("/") or ".." in path
        return False
