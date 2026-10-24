from __future__ import annotations

import base64
import posixpath
import shlex
import threading
import time
import uuid
from abc import abstractmethod
from dataclasses import dataclass

from miniagent.sandbox.base import (
    KILLED_EXIT_CODE,
    TIMEOUT_EXIT_CODE,
    CommandResult,
    Sandbox,
    SandboxError,
)

STATE_DIR = "/tmp/.miniagent"
TRANSPORT_GRACE_S = 15
_KILL_GRACE_S = 2
_MISSING_EXIT_CODE = 44
# One argv entry is capped at 128 KiB on Linux; stay well under it.
_WRITE_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class RawResult:
    stdout: str
    stderr: str
    exit_code: int


def wrap_command(command: str, timeout: int, pidfile: str, cwd: str) -> str:
    """Run `command` as the leader of a new session so that a kill of the
    process group reaches every child, and record the group id for kill."""
    return "\n".join(
        [
            f"mkdir -p {STATE_DIR}",
            f"cd {shlex.quote(cwd)} || exit 1",
            f"setsid timeout -k 5 {int(timeout)} bash -c {shlex.quote(command)} &",
            "pid=$!",
            f"echo $pid > {pidfile}",
            "wait $pid",
            "rc=$?",
            f"rm -f {pidfile}",
            "exit $rc",
        ]
    )


def kill_script(pidfiles: list[str]) -> str:
    targets = " ".join(shlex.quote(p) for p in pidfiles)
    return "\n".join(
        [
            f"for f in {targets}; do",
            '  p=$(cat "$f" 2>/dev/null) && kill -TERM -- "-$p" 2>/dev/null',
            "done",
            f"sleep {_KILL_GRACE_S}",
            f"for f in {targets}; do",
            '  p=$(cat "$f" 2>/dev/null) && kill -KILL -- "-$p" 2>/dev/null',
            '  rm -f "$f"',
            "done",
            "true",
        ]
    )


class ShellSandbox(Sandbox):
    """A sandbox reached through one primitive: run a bash script.

    Opening is lazy and happens on first use, which is always a worker thread,
    so building one on the event loop never blocks on the network."""

    def __init__(self, workspace_dir: str) -> None:
        self.workspace_dir = workspace_dir
        self._open_lock = threading.Lock()
        self._opened = False
        self._lock = threading.Lock()
        self._inflight: set[str] = set()
        self._killed: set[str] = set()

    @abstractmethod
    def _open(self) -> None: ...

    @abstractmethod
    def _exec(
        self, script: str, timeout: int, env: dict[str, str] | None
    ) -> RawResult:
        """Run a bash script. Return non-zero exits; raise SandboxError only
        when the provider cannot run it at all."""

    def ensure_open(self) -> None:
        if self._opened:
            return
        with self._open_lock:
            if not self._opened:
                self._open()
                self._opened = True

    def _abs(self, path: str, workdir: str | None = None) -> str:
        return posixpath.normpath(posixpath.join(self.workspace_dir, workdir or "", path or "."))

    def run_command(
        self,
        command: str,
        timeout: int = 30,
        env: dict[str, str] | None = None,
        workdir: str | None = None,
    ) -> CommandResult:
        start = time.perf_counter()
        cmd_id = uuid.uuid4().hex
        pidfile = f"{STATE_DIR}/{cmd_id}.pid"
        with self._lock:
            self._inflight.add(cmd_id)
        try:
            self.ensure_open()
            with self._lock:
                stopped_while_opening = cmd_id in self._killed
            if stopped_while_opening:
                raw = RawResult(stdout="", stderr="Stopped before the command started", exit_code=0)
            else:
                raw = self._exec(
                    wrap_command(command, timeout, pidfile, self._abs(".", workdir)),
                    timeout + TRANSPORT_GRACE_S,
                    env,
                )
        finally:
            with self._lock:
                self._inflight.discard(cmd_id)
                killed = cmd_id in self._killed
                self._killed.discard(cmd_id)
        elapsed = round((time.perf_counter() - start) * 1000)
        if killed:
            return CommandResult(
                stdout=raw.stdout, stderr=raw.stderr, exit_code=KILLED_EXIT_CODE,
                duration_ms=elapsed,
            )
        if raw.exit_code == TIMEOUT_EXIT_CODE:
            return CommandResult(
                stdout=raw.stdout,
                stderr=f"{raw.stderr}Command timed out after {timeout}s",
                exit_code=TIMEOUT_EXIT_CODE,
                duration_ms=elapsed,
            )
        return CommandResult(
            stdout=raw.stdout, stderr=raw.stderr, exit_code=raw.exit_code,
            duration_ms=elapsed,
        )

    def kill_running(self) -> None:
        with self._lock:
            ids = list(self._inflight)
            self._killed.update(ids)
        if not ids or not self._opened:
            return
        try:
            self._exec(
                kill_script([f"{STATE_DIR}/{i}.pid" for i in ids]),
                _KILL_GRACE_S + TRANSPORT_GRACE_S,
                None,
            )
        except SandboxError:
            pass

    def write_file(self, path: str, content: str, workdir: str | None = None) -> None:
        self.ensure_open()
        target = self._abs(path, workdir)
        tmp = f"{target}.miniagent-{uuid.uuid4().hex[:8]}"
        data = content.encode("utf-8")
        chunks = [data[i : i + _WRITE_CHUNK_BYTES] for i in range(0, len(data), _WRITE_CHUNK_BYTES)] or [b""]
        for index, chunk in enumerate(chunks):
            encoded = base64.b64encode(chunk).decode("ascii")
            redirect = ">" if index == 0 else ">>"
            prefix = f"mkdir -p {shlex.quote(posixpath.dirname(target))} && " if index == 0 else ""
            self._check(
                f"{prefix}printf %s {shlex.quote(encoded)} | base64 -d {redirect} {shlex.quote(tmp)}",
                f"write {path}",
            )
        self._check(f"mv -f {shlex.quote(tmp)} {shlex.quote(target)}", f"write {path}")

    def read_file(self, path: str, workdir: str | None = None) -> str:
        self.ensure_open()
        target = shlex.quote(self._abs(path, workdir))
        raw = self._exec(
            f"[ -f {target} ] || exit {_MISSING_EXIT_CODE}\nbase64 < {target}", 120, None
        )
        if raw.exit_code == _MISSING_EXIT_CODE:
            raise FileNotFoundError(path)
        if raw.exit_code != 0:
            raise OSError(f"read {path} failed: {raw.stderr.strip()}")
        return base64.b64decode("".join(raw.stdout.split())).decode("utf-8")

    def list_files(self, path: str, workdir: str | None = None) -> list[str]:
        self.ensure_open()
        target = shlex.quote(self._abs(path, workdir))
        raw = self._exec(f"[ -d {target} ] || exit 0\nls -1A {target}", 60, None)
        if raw.exit_code != 0:
            raise OSError(f"list {path} failed: {raw.stderr.strip()}")
        return sorted(line for line in raw.stdout.splitlines() if line)

    def _check(self, script: str, what: str) -> None:
        raw = self._exec(script, 120, None)
        if raw.exit_code != 0:
            raise OSError(f"{what} failed: {raw.stderr.strip()}")
