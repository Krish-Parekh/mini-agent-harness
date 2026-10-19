from __future__ import annotations

import os
import signal
from pathlib import Path
import subprocess
import threading
import time

from miniagent.sandbox.base import (
    KILLED_EXIT_CODE,
    TIMEOUT_EXIT_CODE,
    CommandResult,
    Sandbox,
)



def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


class LocalSandbox(Sandbox):
    provider = "local"

    def __init__(self, workspace_dir: str | None = None):
        self.workspace_dir = str(Path(workspace_dir or Path.cwd()).resolve())
        Path(self.workspace_dir).mkdir(parents=True, exist_ok=True)
        self._procs: set[subprocess.Popen] = set()
        self._killed: set[subprocess.Popen] = set()
        self._lock = threading.Lock()

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        return Path(self.workspace_dir).joinpath(p)

    def run_command(
        self, command: str, timeout: int = 30, env: dict[str, str] | None = None
    ) -> CommandResult:
        start = time.perf_counter()
        proc_env = {**os.environ, **env} if env else None
        if "git init" in command:
            template = Path(self.workspace_dir) / ".miniagent-empty-git-template"
            template.mkdir(exist_ok=True)
            proc_env = {**(proc_env or os.environ), "GIT_TEMPLATE_DIR": str(template)}
        # Popen (not subprocess.run) so kill_running() can reach the live process.
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=self.workspace_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=proc_env,
            start_new_session=True,
        )
        with self._lock:
            self._procs.add(proc)

        def elapsed() -> int:
            return round((time.perf_counter() - start) * 1000)

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            stdout, stderr = proc.communicate()
            return CommandResult(
                stdout=stdout,
                stderr=f"{stderr}Command timed out after {timeout}s",
                exit_code=TIMEOUT_EXIT_CODE,
                duration_ms=elapsed(),
            )
        finally:
            with self._lock:
                self._procs.discard(proc)
                killed = proc in self._killed
                self._killed.discard(proc)
        return CommandResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=KILLED_EXIT_CODE if killed else proc.returncode,
            duration_ms=elapsed(),
        )

    def kill_running(self) -> None:
        with self._lock:
            procs = [p for p in self._procs if p.poll() is None]
            self._killed.update(procs)
        for proc in procs:
            _kill_group(proc)

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
