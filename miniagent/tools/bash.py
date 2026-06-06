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

    def to_llm_text(self) -> str:
        parts = [f"exit_code: {self.exit_code}"]
        if self.stdout:
            parts.append(f"stdout:\n{self.stdout}")
        if self.stderr:
            parts.append(f"stderr:\n{self.stderr}")
        return "\n".join(parts)


class BashTool(Tool):
    name = "bash"
    description = "Run a shell command in the workspace and return its output."
    action_type = BashAction
    observation_type = BashObservation

    def execute(self, action: BashAction, sandbox: Sandbox) -> BashObservation:
        result = sandbox.run_command(action.command, timeout=action.timeout)
        return BashObservation(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
        )
