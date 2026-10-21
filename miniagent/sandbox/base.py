from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

TIMEOUT_EXIT_CODE = 124
KILLED_EXIT_CODE = 130


class CommandResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int = 0


class SandboxError(Exception):
    pass


class SandboxExpired(SandboxError):
    pass


class Sandbox(ABC):
    """Where the agent's tools run.

    Contract shared by every provider: a non-zero exit is returned, never
    raised; a timeout returns TIMEOUT_EXIT_CODE; a command stopped by
    kill_running returns KILLED_EXIT_CODE; relative paths resolve against
    workspace_dir. kill_running must stop every command in flight, because
    parallel-safe tool calls and fanout workers share one sandbox."""

    provider: ClassVar[str]
    workspace_dir: str
    sandbox_id: str | None = None

    @abstractmethod
    def run_command(
        self, command: str, timeout: int = 30, env: dict[str, str] | None = None
    ) -> CommandResult: ...

    @abstractmethod
    def write_file(self, path: str, content: str) -> None: ...

    @abstractmethod
    def read_file(self, path: str) -> str: ...

    @abstractmethod
    def list_files(self, path: str) -> list[str]: ...

    def kill_running(self) -> None:
        """Best-effort: terminate every command currently running."""

    def set_working_dir(self, path: str) -> None:
        self.workspace_dir = path

    def extend(self, seconds: int) -> None:
        """Push the provider's deadline forward. No-op where nothing expires."""

    def stop_if_idle(self, idle_s: int) -> bool:
        return False

    @abstractmethod
    def close(self) -> None: ...
