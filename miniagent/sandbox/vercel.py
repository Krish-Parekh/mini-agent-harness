from __future__ import annotations

from miniagent.sandbox.base import SandboxError, SandboxExpired
from miniagent.sandbox.shell import RawResult, ShellSandbox


class VercelSandbox(ShellSandbox):
    """Vercel Firecracker sandbox. The default `universal` image ships git.
    The sandbox name is its id, so reconnect is by name."""

    provider = "vercel"

    def __init__(
        self,
        *,
        lifetime_s: int = 2700,
        cpus: float = 2,
        sandbox_id: str | None = None,
        name: str | None = None,
        workspace_dir: str = "/vercel/sandbox/workspace",
    ) -> None:
        super().__init__(workspace_dir)
        self.sandbox_id = sandbox_id
        self._lifetime_s = lifetime_s
        # Vercel accepts 1 or an even number of vCPUs.
        vcpus = max(1, int(cpus))
        self._vcpus = vcpus if vcpus == 1 or vcpus % 2 == 0 else vcpus + 1
        self._name = name
        self._client = None
        self._box = None

    def _open(self) -> None:
        from vercel.sandbox.sync import SandboxApiError, SandboxResources, SyncSandboxClient

        self._client = SyncSandboxClient.create()
        try:
            if self.sandbox_id:
                self._box = self._client.get_sandbox(name=self.sandbox_id)
                return
            self._box = self._client.create_sandbox(
                name=self._name,
                execution_time_limit=self._lifetime_s,
                resources=SandboxResources(vcpus=self._vcpus),
                persistent=False,
                env={"GIT_TERMINAL_PROMPT": "0"},
                tags={"app": "miniagent"},
            )
            self.sandbox_id = self._box.name
            self._box.run_process("mkdir", ["-p", self.workspace_dir], capture_output=True)
        except SandboxApiError as exc:
            if "404" in str(exc) or "not found" in str(exc).lower():
                raise SandboxExpired(f"vercel sandbox {self.sandbox_id} is gone") from exc
            raise SandboxError(f"vercel sandbox setup failed: {exc}") from exc

    def _exec(self, script, timeout, env) -> RawResult:
        from vercel.sandbox.sync import SandboxError as VercelError

        try:
            result = self._box.run_process(
                "bash", ["-c", script], env=env or None, kill_after=timeout, capture_output=True
            )
        except VercelError as exc:
            raise SandboxError(f"vercel command failed: {exc}") from exc
        return RawResult(
            stdout=result.stdout or "", stderr=result.stderr or "", exit_code=result.returncode
        )

    def extend(self, seconds: int) -> None:
        if self._box is not None:
            try:
                self._box.extend_execution_time_limit(seconds)
            except Exception:
                pass

    def close(self) -> None:
        try:
            if self._box is None and self.sandbox_id:
                from vercel.sandbox.sync import SyncSandboxClient

                self._client = SyncSandboxClient.create()
                self._box = self._client.get_sandbox(name=self.sandbox_id)
            if self._box is not None:
                self._box.destroy(delete_orphan_snapshots=True)
        except Exception:
            pass
        finally:
            if self._client is not None:
                self._client.close()
