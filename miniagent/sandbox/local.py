from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time

from miniagent.sandbox.base import Sandbox, CommandResult


class LocalSandbox(Sandbox):
    def __init__(self, workspace_dir: str | None = None):
        self.workspace_dir = str(Path(workspace_dir or Path.cwd()).resolve())
        Path(self.workspace_dir).mkdir(parents=True, exist_ok=True)
        self._proc: subprocess.Popen | None = None

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        return Path(self.workspace_dir).joinpath(p)

    def run_command(self, command: str, timeout: int = 30) -> CommandResult:
        start = time.perf_counter()
        env = None
        if "git init" in command:
            template = Path(self.workspace_dir) / ".miniagent-empty-git-template"
            template.mkdir(exist_ok=True)
            env = {**os.environ, "GIT_TEMPLATE_DIR": str(template)}
        # Popen (not subprocess.run) so kill_running() can reach the live process.
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=self.workspace_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self._proc = proc

        def elapsed() -> int:
            return round((time.perf_counter() - start) * 1000)

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            return CommandResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=proc.returncode,
                duration_ms=elapsed(),
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return CommandResult(
                stdout="",
                stderr="Command timed out",
                exit_code=1,
                duration_ms=elapsed(),
            )
        finally:
            self._proc = None

    def kill_running(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.kill()

    def write_file(self, path: str, content: str) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def read_file(self, path: str) -> str:
        return self._resolve(path).read_text()

    def list_files(self, path: str) -> list[str]:
        target = self._resolve(path)
        if not target.exists():
            return []
        return sorted(p.name for p in target.iterdir())

    def set_working_dir(self, path: str) -> None:
        target = Path(path)
        if not target.is_absolute():
            target = Path(self.workspace_dir).joinpath(target)
        if not target.exists():
            raise FileNotFoundError(f"Working directory {path} does not exist")
        self.workspace_dir = str(target.resolve())

    def close(self) -> None:
        pass
