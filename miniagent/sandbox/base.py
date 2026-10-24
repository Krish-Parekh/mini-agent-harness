from __future__ import annotations

import posixpath
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
    workspace_dir, or against workdir when one is given (itself resolved
    against workspace_dir). kill_running must stop every command in flight,
    because parallel-safe tool calls and task workers share one sandbox."""

    provider: ClassVar[str]
    workspace_dir: str
    sandbox_id: str | None = None

    @abstractmethod
    def run_command(
        self,
        command: str,
        timeout: int = 30,
        env: dict[str, str] | None = None,
        workdir: str | None = None,
    ) -> CommandResult: ...

    @abstractmethod
    def write_file(self, path: str, content: str, workdir: str | None = None) -> None: ...

    @abstractmethod
    def read_file(self, path: str, workdir: str | None = None) -> str: ...

    @abstractmethod
    def list_files(self, path: str, workdir: str | None = None) -> list[str]: ...

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


class WorkdirView(Sandbox):
    def __init__(self, parent: Sandbox, workdir: str) -> None:
        self.parent = parent
        self.provider = parent.provider
        self.sandbox_id = parent.sandbox_id
        self.workspace_dir = posixpath.join(parent.workspace_dir, workdir)

    def _dir(self, workdir: str | None) -> str:
        return posixpath.join(self.workspace_dir, workdir or "")

    def run_command(self, command, timeout=30, env=None, workdir=None) -> CommandResult:
        return self.parent.run_command(command, timeout, env, self._dir(workdir))

    def write_file(self, path, content, workdir=None) -> None:
        self.parent.write_file(path, content, self._dir(workdir))

    def read_file(self, path, workdir=None) -> str:
        return self.parent.read_file(path, self._dir(workdir))

    def list_files(self, path, workdir=None) -> list[str]:
        return self.parent.list_files(path, self._dir(workdir))

    def kill_running(self) -> None:
        self.parent.kill_running()

    def close(self) -> None:
        pass
