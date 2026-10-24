from __future__ import annotations

import posixpath
import shlex

from pydantic import Field

from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool
from miniagent.tools.bash import inside_workspace

MAX_FILES = 100
MAX_LINES = 250
SEARCH_TIMEOUT = 30


class SearchObservation(Observation):
    text: str
    error: bool = False

    def to_llm_text(self) -> str:
        return f"ERROR: {self.text}" if self.error else self.text


class GrepAction(Action):
    pattern: str = Field(description="Regular expression to search for (ripgrep syntax).")
    path: str = Field(
        ".", description="File or directory to search. Relative paths resolve against the workspace."
    )
    include: str | None = Field(
        None, description="Only search files matching this glob, e.g. '*.py' or '*.{ts,tsx}'."
    )


class GlobAction(Action):
    pattern: str = Field(
        description="Glob matched against workspace-relative paths, e.g. '*.py' "
        "(any depth) or 'src/**/*.test.ts'."
    )
    path: str = Field(
        ".", description="Directory to search. Relative paths resolve against the workspace."
    )


class GrepTool(Tool):
    name = "grep"
    description = (
        "Search file contents with a ripgrep regular expression. Returns matching "
        "lines with line numbers, grouped by file. Use this instead of `grep` or "
        "`rg` in bash. Narrow with `path` and `include`. Hidden files are "
        f"searched; gitignored files are skipped. Output stops at {MAX_LINES} lines."
    )
    action_type = GrepAction
    observation_type = SearchObservation

    def __init__(self, confined: bool = True) -> None:
        self.confined = confined

    def execute(self, action: GrepAction, sandbox: Sandbox) -> SearchObservation:
        args = ["--heading", "--line-number", "--max-columns=300", "--max-columns-preview"]
        if action.include:
            args.append(f"--glob={action.include}")
        args.append(f"--regexp={action.pattern}")
        return _ripgrep(args, action.path, sandbox, MAX_LINES, self.confined)


class GlobTool(Tool):
    name = "glob"
    description = (
        "Find files whose paths match a glob pattern. Use this instead of `find` "
        "or `ls -R` in bash. Hidden files are listed; gitignored files are "
        f"skipped. Output stops at {MAX_FILES} files."
    )
    action_type = GlobAction
    observation_type = SearchObservation

    def __init__(self, confined: bool = True) -> None:
        self.confined = confined

    def execute(self, action: GlobAction, sandbox: Sandbox) -> SearchObservation:
        args = ["--files", f"--glob={action.pattern}"]
        return _ripgrep(args, action.path, sandbox, MAX_FILES, self.confined)


def _ripgrep(
    args: list[str], path: str, sandbox: Sandbox, limit: int, confined: bool
) -> SearchObservation:
    root = posixpath.normpath(sandbox.workspace_dir)
    target = posixpath.normpath(posixpath.join(root, path))
    inside = inside_workspace(path, root) is not None
    if confined and not inside:
        return SearchObservation(text=f"{path} is outside the workspace.", error=True)
    if target != root:
        args = [*args, "--", posixpath.relpath(target, root) if inside else target]
    command = shlex.join(["rg", "--color=never", "--hidden", "--glob=!.git", *args])
    result = sandbox.run_command(command, timeout=SEARCH_TIMEOUT)
    if result.exit_code == 1:
        return SearchObservation(text="No matches.")
    if result.exit_code != 0:
        return SearchObservation(text=result.stderr.strip(), error=True)
    lines = result.stdout.splitlines()
    if len(lines) > limit:
        lines = lines[:limit] + [f"[Output stopped at {limit} lines. Narrow the path or pattern.]"]
    return SearchObservation(text="\n".join(lines))
