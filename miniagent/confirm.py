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

# Commands that modify the workspace without being "risky" — used to keep plan
# mode read-only at the tool layer. Pure exploration (rg, cat, find, git
# log/diff/status, sed -n) must NOT match.
MUTATING_BASH_PATTERNS = [
    r"(?<![\d&])>>?\s*(?!/dev/null)[\w./~'\"$]",  # write redirect (not 2>, >&, /dev/null)
    r"\btee\b",
    r"\b(rm|mv|cp|mkdir|touch|chmod|chown|ln)\b",
    r"\bsed\b.*\s-i\b",                            # in-place sed
    r"\bgit\s+(add|commit|push|pull|checkout|switch|restore|merge|rebase|stash|clean|cherry-pick|revert|reset|rm|mv)\b",
    r"\b(npm|pnpm|yarn|pip3?|uv|poetry|cargo)\s+(install|add|remove|uninstall|update|upgrade)\b",
]


def blocked_in_plan_mode(action_event: ActionEvent) -> bool:
    """Read-only enforcement while planning: block workspace mutations at the
    tool layer instead of trusting the prompt. Lean heuristic — the plan-mode
    directive covers whatever slips through."""
    if action_event.tool_name == "file_edit":
        return action_event.arguments.get("command") in ("create", "str_replace")
    if action_event.tool_name == "bash":
        command = action_event.arguments.get("command", "")
        patterns = RISKY_PATTERNS + MUTATING_BASH_PATTERNS
        return any(re.search(p, command, re.IGNORECASE) for p in patterns)
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
        if action_event.tool_name == "bash":
            command = action_event.arguments.get("command", "")
            return any(re.search(p, command, re.IGNORECASE) for p in RISKY_PATTERNS)
        if action_event.tool_name == "file_edit":
            path = action_event.arguments.get("path", "")
            return path.startswith("/") or ".." in path
        return False
