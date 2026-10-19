from __future__ import annotations

from miniagent.sandbox.base import TIMEOUT_EXIT_CODE, SandboxError, SandboxExpired
from miniagent.sandbox.shell import RawResult, ShellSandbox

_IDLE_TIMEOUT_S = 900


class ModalSandbox(ShellSandbox):
    """Modal gVisor sandbox. Files go through the shell because Modal's file
    API has changed across releases and its old open() is deprecated."""

    provider = "modal"

    def __init__(
        self,
        *,
        app_name: str = "miniagent",
        lifetime_s: int = 3600,
        cpus: float = 2,
        memory_mb: int = 4096,
        sandbox_id: str | None = None,
        name: str | None = None,
        workspace_dir: str = "/workspace",
    ) -> None:
        super().__init__(workspace_dir)
        self.sandbox_id = sandbox_id
        self._app_name = app_name
        self._lifetime_s = lifetime_s
        self._cpus = cpus
        self._memory_mb = memory_mb
        self._name = name
        self._sb = None

    def _open(self) -> None:
        import modal
        import modal.exception

        try:
            if self.sandbox_id:
                self._sb = modal.Sandbox.from_id(self.sandbox_id)
                if self._sb.poll() is not None:
                    raise SandboxExpired(f"modal sandbox {self.sandbox_id} has stopped")
                return
            app = modal.App.lookup(self._app_name, create_if_missing=True)
            image = modal.Image.debian_slim(python_version="3.12").apt_install(
                "git", "procps", "util-linux", "ca-certificates", "curl"
            )
            self._sb = modal.Sandbox.create(
                app=app,
                image=image,
                timeout=self._lifetime_s,
                idle_timeout=_IDLE_TIMEOUT_S,
                cpu=self._cpus,
                memory=self._memory_mb,
                env={"GIT_TERMINAL_PROMPT": "0"},
                tags={"app": "miniagent", "conversation": self._name or ""},
            )
            self.sandbox_id = self._sb.object_id
            self._sb.exec("mkdir", "-p", self.workspace_dir).wait()
        except modal.exception.NotFoundError as exc:
            raise SandboxExpired(f"modal sandbox {self.sandbox_id} is gone") from exc
        except modal.exception.Error as exc:
            raise SandboxError(f"modal sandbox setup failed: {exc}") from exc

    def _exec(self, script, timeout, env) -> RawResult:
        import modal.exception

        try:
            process = self._sb.exec("bash", "-c", script, timeout=timeout, env=env or None)
            stdout = process.stdout.read()
            stderr = process.stderr.read()
            code = process.wait()
        except modal.exception.Error as exc:
            raise SandboxError(f"modal command failed: {exc}") from exc
        # Modal reports an exec timeout as -1 rather than raising.
        if code == -1:
            code = TIMEOUT_EXIT_CODE
        return RawResult(stdout=stdout, stderr=stderr, exit_code=code)

    def close(self) -> None:
        try:
            if self._sb is None and self.sandbox_id:
                import modal

                self._sb = modal.Sandbox.from_id(self.sandbox_id)
            if self._sb is not None:
                self._sb.terminate()
        except Exception:
            pass
