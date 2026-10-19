from __future__ import annotations

import shlex
import uuid

from miniagent.sandbox.base import TIMEOUT_EXIT_CODE, SandboxError, SandboxExpired
from miniagent.sandbox.shell import STATE_DIR, RawResult, ShellSandbox

_AUTO_STOP_MINUTES = 30
_STOPPED = ("stopped", "archived")


class DaytonaSandbox(ShellSandbox):
    """Daytona sandbox. exec() returns one merged output string, so stderr is
    sent to a file and appended after a marker that the adapter splits on."""

    provider = "daytona"

    def __init__(
        self,
        *,
        image: str | None = None,
        cpus: float = 2,
        memory_mb: int = 4096,
        sandbox_id: str | None = None,
        name: str | None = None,
        workspace_dir: str | None = None,
    ) -> None:
        super().__init__(workspace_dir or "")
        self.sandbox_id = sandbox_id
        self._image = image
        self._cpus = cpus
        self._memory_mb = memory_mb
        self._name = name
        self._client = None
        self._sbx = None

    def _open(self) -> None:
        from daytona import (
            CreateSandboxFromImageParams,
            CreateSandboxFromSnapshotParams,
            Daytona,
            DaytonaError,
            DaytonaNotFoundError,
            Resources,
        )

        self._client = Daytona()
        try:
            if self.sandbox_id:
                self._sbx = self._client.get(self.sandbox_id)
                if str(self._sbx.state).lower().endswith(_STOPPED):
                    self._sbx.start(timeout=180)
            else:
                common = {
                    "name": self._name,
                    "labels": {"app": "miniagent"},
                    "env_vars": {"GIT_TERMINAL_PROMPT": "0"},
                    "auto_stop_interval": _AUTO_STOP_MINUTES,
                }
                if self._image:
                    params = CreateSandboxFromImageParams(
                        image=self._image,
                        resources=Resources(cpu=int(self._cpus), memory=max(1, self._memory_mb // 1024)),
                        **common,
                    )
                else:
                    params = CreateSandboxFromSnapshotParams(**common)
                self._sbx = self._client.create(params, timeout=180)
                self.sandbox_id = self._sbx.id
        except DaytonaNotFoundError as exc:
            raise SandboxExpired(f"daytona sandbox {self.sandbox_id} is gone") from exc
        except DaytonaError as exc:
            raise SandboxError(f"daytona sandbox setup failed: {exc}") from exc
        if not self.workspace_dir:
            self.workspace_dir = f"{self._sbx.get_work_dir().rstrip('/')}/workspace"
        setup = self._exec(
            f"mkdir -p {shlex.quote(self.workspace_dir)}\n"
            "command -v git >/dev/null || (sudo -n apt-get update -qq && sudo -n apt-get install -y -qq git) >/dev/null 2>&1\n"
            "command -v git >/dev/null && command -v setsid >/dev/null && command -v timeout >/dev/null",
            300,
            None,
        )
        if setup.exit_code != 0:
            raise SandboxError(
                "daytona sandbox lacks git, setsid or timeout; set MINIAGENT_DAYTONA_IMAGE to an image that has them"
            )

    def _exec(self, script, timeout, env) -> RawResult:
        from daytona import DaytonaError, DaytonaProcessExecutionTimeoutError

        marker = f"__MINIAGENT_STDERR_{uuid.uuid4().hex}__"
        errfile = f"{STATE_DIR}/{uuid.uuid4().hex}.err"
        command = "\n".join(
            [
                f"mkdir -p {STATE_DIR}",
                f"bash -c {shlex.quote(script)} 2>{errfile}",
                "rc=$?",
                f"printf '%s' {marker}",
                f"cat {errfile} 2>/dev/null",
                f"rm -f {errfile}",
                "exit $rc",
            ]
        )
        try:
            response = self._sbx.process.exec(
                f"bash -c {shlex.quote(command)}", env=env or None, timeout=timeout
            )
        except DaytonaProcessExecutionTimeoutError:
            return RawResult(stdout="", stderr="", exit_code=TIMEOUT_EXIT_CODE)
        except DaytonaError as exc:
            raise SandboxError(f"daytona command failed: {exc}") from exc
        output = response.result or ""
        stdout, _, stderr = output.partition(marker)
        return RawResult(stdout=stdout, stderr=stderr, exit_code=int(response.exit_code))

    def extend(self, seconds: int) -> None:
        if self._sbx is not None:
            try:
                self._sbx.refresh_activity()
            except Exception:
                pass

    def close(self) -> None:
        try:
            if self._sbx is None and self.sandbox_id:
                from daytona import Daytona

                self._sbx = Daytona().get(self.sandbox_id)
            if self._sbx is not None:
                self._sbx.delete()
        except Exception:
            pass
