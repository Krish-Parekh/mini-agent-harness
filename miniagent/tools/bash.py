from __future__ import annotations

from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool


class BashAction(Action):
    command: str
    timeout: int = 30


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
        "git work. Keep output small — prefer `| head -50` and narrow test "
        "invocations over full suites. Never start interactive commands "
        "(editors, REPLs, watch mode). The default `timeout` is 30 seconds; "
        "pass a larger value (120-600) for installs, builds, or test suites."
    )
    action_type = BashAction
    observation_type = BashObservation

    def execute(self, action: BashAction, sandbox: Sandbox) -> BashObservation:
        result = sandbox.run_command(action.command, timeout=action.timeout)
        return BashObservation(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
        )
