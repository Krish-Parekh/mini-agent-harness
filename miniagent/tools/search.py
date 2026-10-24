from __future__ import annotations

import posixpath
import shlex

from pydantic import Field

from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool

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
    path: str = Field(".", description="File or directory to search, relative to the workspace.")
    include: str | None = Field(
        None, description="Only search files matching this glob, e.g. '*.py' or '*.{ts,tsx}'."
    )


class GlobAction(Action):
    pattern: str = Field(
        description="Glob matched against workspace-relative paths, e.g. '*.py' "
        "(any depth) or 'src/**/*.test.ts'."
    )
    path: str = Field(".", description="Directory to search, relative to the workspace.")


class GrepTool(Tool):
    name = "grep"
    description = (
        "Search file contents with a ripgrep regular expression. Returns matching "
        "lines with line numbers, grouped by file. Use this instead of `grep` or "
        "`rg` in the terminal. Narrow with `path` and `include`. Gitignored files are "
        f"skipped. Output stops at {MAX_LINES} lines."
    )
    action_type = GrepAction
    observation_type = SearchObservation

    def execute(self, action: GrepAction, sandbox: Sandbox) -> SearchObservation:
        args = ["--heading", "--line-number", "--max-columns=300", "--max-columns-preview"]
        if action.include:
            args.append(f"--glob={action.include}")
        args.append(f"--regexp={action.pattern}")
        return _ripgrep(args, action.path, sandbox, MAX_LINES)


class GlobTool(Tool):
    name = "glob"
    description = (
        "Find files whose paths match a glob pattern, most recently modified "
        "first. Use this instead of `find` or `ls -R` in the terminal. Gitignored files "
        f"are skipped. Output stops at {MAX_FILES} files."
    )
    action_type = GlobAction
    observation_type = SearchObservation

    def execute(self, action: GlobAction, sandbox: Sandbox) -> SearchObservation:
        args = ["--files", f"--glob={action.pattern}", "--sortr=modified"]
        return _ripgrep(args, action.path, sandbox, MAX_FILES)


def _inside_workspace(workdir: str, workspace: str) -> str | None:
    root = posixpath.normpath(workspace)
    target = posixpath.normpath(posixpath.join(root, workdir))
    if target != root and not target.startswith(root + "/"):
        return None
    return target


def _ripgrep(args: list[str], path: str, sandbox: Sandbox, limit: int) -> SearchObservation:
    target = _inside_workspace(path, sandbox.workspace_dir)
    if target is None:
        return SearchObservation(text=f"{path} is outside the workspace.", error=True)
    relative = posixpath.relpath(target, posixpath.normpath(sandbox.workspace_dir))
    if relative != ".":
        args = [*args, "--", relative]
    command = shlex.join(["rg", "--color=never", *args])
    result = sandbox.run_command(command, timeout=SEARCH_TIMEOUT)
    if result.exit_code == 1:
        return SearchObservation(text="No matches.")
    if result.exit_code != 0:
        return SearchObservation(text=result.stderr.strip(), error=True)
    lines = result.stdout.splitlines()
    if len(lines) > limit:
        lines = lines[:limit] + [f"[Output stopped at {limit} lines. Narrow the path or pattern.]"]
    return SearchObservation(text="\n".join(lines))
