from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict


class CommandResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    stdout: str
    stderr: str
    exit_code: int


class Sandbox(ABC):
    @abstractmethod
    def run_command(self, command: str, timeout: int = 30) -> CommandResult: ...

    @abstractmethod
    def write_file(self, path: str, content: str) -> None: ...

    @abstractmethod
    def read_file(self, path: str) -> str: ...

    @abstractmethod
    def list_files(self, path: str) -> list[str]: ...

    @abstractmethod
    def close(self) -> None: ...
