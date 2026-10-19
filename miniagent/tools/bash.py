from __future__ import annotations

import posixpath
import shlex

from pydantic import Field

from miniagent.sandbox.base import CommandResult, Sandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool


class BashAction(Action):
    description: str = Field(
        "", description="5-10 word summary of what the command does, shown to the user."
    )
    command: str
    workdir: str | None = Field(
        None,
        description="Directory to run in, relative to the workspace. Use instead of `cd x && ...`.",
    )
    timeout: int = Field(30, ge=1, le=600)


class BashObservation(Observation):
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int = 0

    def to_llm_text(self) -> str:
        parts = [f"exit_code: {self.exit_code}"]
        if self.stdout:
            parts.append(f"stdout:\n{self.stdout}")
        if self.stderr:
            parts.append(f"stderr:\n{self.stderr}")
        # Spell out the empty case: a bare "exit_code: 0" reads as ambiguous, so
        # the model can't tell a clean no-match run from a broken one and retries.
        if not self.stdout and not self.stderr:
            parts.append("(no output)")
        return "\n".join(parts)


class BashTool(Tool):
    name = "bash"
    description = (
        "Run a shell command and return its stdout, stderr, and exit code. The "
        "command runs non-interactively with the workspace root as the working "
        "directory. Use it to explore (`rg -n \"pattern\" src/`, `git log "
        "--oneline -10`, `git diff`, `sed -n '40,90p' file.py`), to verify "
        "(`python -m pytest tests/test_x.py -x -q`), and for any multi-file or "
        "git work. Keep output small: prefer `| head -50` and narrow test "
        "invocations over full suites. Never start interactive commands "
        "(editors, REPLs, watch mode). The default `timeout` is 30 seconds; "
        "pass a larger value (120-600) for installs, builds, or test suites. "
        "Set `description` to a short summary of the command, and `workdir` "
        "instead of starting the command with `cd`. Before `rm` or `mv`, check "
        "the resolved target path, and guard variables with `${VAR:?}` so an "
        "empty value cannot widen the target. If the sandbox denies a command, "
        "do not retry the same effect another way."
    )
    action_type = BashAction
    observation_type = BashObservation

    def execute(self, action: BashAction, sandbox: Sandbox) -> BashObservation:
        command = action.command
        if action.workdir:
            workdir = _inside_workspace(action.workdir, sandbox.workspace_dir)
            if workdir is None:
                return _rejected(f"workdir {action.workdir} is outside the workspace.")
            command = f"cd -- {shlex.quote(workdir)} && {command}"
        result = sandbox.run_command(command, timeout=action.timeout)
        return _observation(result)


def _inside_workspace(workdir: str, workspace: str) -> str | None:
    root = posixpath.normpath(workspace)
    target = posixpath.normpath(posixpath.join(root, workdir))
    if target != root and not target.startswith(root + "/"):
        return None
    return target


def _rejected(message: str) -> BashObservation:
    return BashObservation(stdout="", stderr=message, exit_code=2)


def _observation(result: CommandResult) -> BashObservation:
    return BashObservation(
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
    )
