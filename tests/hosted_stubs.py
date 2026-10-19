from __future__ import annotations

import subprocess
from dataclasses import dataclass

IMAGE = "miniagent-sandbox:latest"


class Container:
    """A throwaway container that stands in for a provider's VM, so each
    adapter's translation of its SDK runs against real bash, setsid and git."""

    def __init__(self) -> None:
        self.id = subprocess.run(
            ["docker", "run", "-d", "--init", "--label", "miniagent.stub=1", IMAGE, "sleep", "infinity"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    def run(
        self, argv: list[str], env: dict | None = None, stdin: str | None = None
    ) -> subprocess.CompletedProcess:
        args = ["docker", "exec", "-i"]
        for k, v in (env or {}).items():
            args += ["-e", f"{k}={v}"]
        return subprocess.run(args + [self.id, *argv], capture_output=True, text=True, input=stdin)

    def remove(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.id], capture_output=True)


@dataclass
class _Done:
    stdout: str
    stderr: str
    returncode: int


class E2BStub:
    """Mirrors e2b.Sandbox: commands.run raises CommandExitException on a
    non-zero exit, and files.* work on absolute paths."""

    def __init__(self, box: Container) -> None:
        self.commands = self
        self.files = self
        self._box = box

    def run(self, cmd, envs=None, timeout=60):
        from e2b import CommandExitException
        from e2b.sandbox.commands.command_handle import CommandResult

        done = self._box.run(["bash", "-c", cmd], envs)
        if done.returncode != 0:
            raise CommandExitException(done.stderr, done.stdout, done.returncode, None)
        return CommandResult(done.stderr, done.stdout, 0, None)

    def write(self, path, data):
        self._box.run(["bash", "-c", 'mkdir -p "$(dirname "$1")" && cat > "$1"', "_", path], stdin=data)

    def read(self, path):
        from e2b import FileNotFoundException

        done = self._box.run(["cat", path])
        if done.returncode != 0:
            raise FileNotFoundException(path)
        return done.stdout

    def list(self, path, depth=1):
        from e2b import NotFoundException

        done = self._box.run(["ls", "-1A", path])
        if done.returncode != 0:
            raise NotFoundException(path)
        return [type("Entry", (), {"name": n}) for n in done.stdout.splitlines() if n]

    def kill(self):
        self._box.remove()


class _ModalProcess:
    def __init__(self, done, timed_out: bool) -> None:
        self.stdout = type("R", (), {"read": lambda _s: done.stdout})()
        self.stderr = type("R", (), {"read": lambda _s: done.stderr})()
        self._code = -1 if timed_out else done.returncode

    def wait(self):
        return self._code


class ModalStub:
    """Mirrors modal.Sandbox.exec: argv in, process handle out, -1 on timeout."""

    def __init__(self, box: Container, force_timeout: bool = False) -> None:
        self._box = box
        self._force_timeout = force_timeout

    def exec(self, *args, timeout=None, env=None):
        return _ModalProcess(self._box.run(list(args), env), self._force_timeout)

    def terminate(self):
        self._box.remove()


class VercelStub:
    """Mirrors vercel SyncSandbox.run_process with capture_output."""

    def __init__(self, box: Container) -> None:
        self._box = box

    def run_process(self, command, args=None, *, env=None, kill_after=None, capture_output=False):
        done = self._box.run([command, *(args or [])], env)
        return _Done(done.stdout, done.stderr, done.returncode)

    def destroy(self, delete_orphan_snapshots=False):
        self._box.remove()


class DaytonaStub:
    """Mirrors daytona Sandbox.process.exec: one merged output string."""

    def __init__(self, box: Container) -> None:
        self.process = self
        self._box = box

    def exec(self, command, env=None, timeout=None):
        done = self._box.run(["sh", "-c", command], env)
        return type("Resp", (), {"result": done.stdout + done.stderr, "exit_code": done.returncode})()

    def delete(self):
        self._box.remove()
