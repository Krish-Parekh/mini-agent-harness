from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict


class CommandResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int = 0


class Sandbox(ABC):
    workspace_dir: str

    @abstractmethod
    def run_command(self, command: str, timeout: int = 30) -> CommandResult: ...

    @abstractmethod
    def write_file(self, path: str, content: str) -> None: ...

    @abstractmethod
    def read_file(self, path: str) -> str: ...

    @abstractmethod
    def list_files(self, path: str) -> list[str]: ...

    def kill_running(self) -> None:
        """Best-effort: terminate the command currently running, if any.

        Default is a no-op; sandboxes that can interrupt an in-flight command
        (e.g. the local one) override this so a user stop is responsive."""

    @abstractmethod
    def close(self) -> None: ...
