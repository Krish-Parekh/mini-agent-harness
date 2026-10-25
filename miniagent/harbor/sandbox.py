from __future__ import annotations

import asyncio
import posixpath
import shlex
import tempfile
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar

from harbor.environments.base import BaseEnvironment

from miniagent.sandbox.base import CommandResult, SandboxError
from miniagent.sandbox.shell import RawResult, ShellSandbox

T = TypeVar("T")


class HarborSandbox(ShellSandbox):
    provider = "harbor"

    def __init__(
        self,
        environment: BaseEnvironment,
        loop: asyncio.AbstractEventLoop,
        workspace_dir: str,
    ) -> None:
        super().__init__(workspace_dir)
        self._environment = environment
        self._loop = loop
        self._closed = False

    @classmethod
    async def connect(cls, environment: BaseEnvironment) -> HarborSandbox:
        result = await environment.exec("pwd")
        return cls(environment, asyncio.get_running_loop(), (result.stdout or "").strip())

    def _call(self, coroutine: Coroutine[Any, Any, T]) -> T:
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result()

    def _open(self) -> None:
        pass

    def _exec(self, script: str, timeout: int, env: dict[str, str] | None) -> RawResult:
        result = self._call(self._environment.exec(script, env=env, timeout_sec=timeout))
        return RawResult(
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            exit_code=result.return_code,
        )

    def run_command(
        self,
        command: str,
        timeout: int = 30,
        env: dict[str, str] | None = None,
        workdir: str | None = None,
    ) -> CommandResult:
        self._raise_if_closed()
        return super().run_command(command, timeout, env, workdir)

    def write_file(self, path: str, content: str, workdir: str | None = None) -> None:
        self._raise_if_closed()
        target = self._abs(path, workdir)
        self._check(f"mkdir -p {shlex.quote(posixpath.dirname(target))}", f"write {path}")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / posixpath.basename(target)
            source.write_text(content)
            self._call(self._environment.upload_file(source, target))
        user = self._environment.default_user
        if user is not None:
            self._call(
                self._environment.exec(
                    f"chown {shlex.quote(str(user))} {shlex.quote(target)}", user="root"
                )
            )

    def _raise_if_closed(self) -> None:
        if self._closed:
            raise SandboxError("Harbor ended the agent run")

    def close(self) -> None:
        self._closed = True
