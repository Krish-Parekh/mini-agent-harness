from __future__ import annotations

import os

from miniagent.sandbox.base import SandboxError, SandboxExpired
from miniagent.sandbox.shell import RawResult, ShellSandbox

LABEL = "miniagent.sandbox"


class DockerSandbox(ShellSandbox):
    """A long-lived container per Conversation. Host paths in `mounts` are
    bind-mounted at the same absolute path, so a host git worktree (whose
    .git file points at the shared clone by absolute path) works unchanged."""

    provider = "docker"

    def __init__(
        self,
        *,
        workspace_dir: str,
        image: str,
        mounts: list[str],
        sandbox_id: str | None = None,
        name: str | None = None,
        cpus: float = 2,
        memory_mb: int = 4096,
    ) -> None:
        super().__init__(workspace_dir)
        self.sandbox_id = sandbox_id
        self._image = image
        self._mounts = mounts
        self._name = name
        self._cpus = cpus
        self._memory_mb = memory_mb
        self._client = None
        self._container = None

    def _docker(self):
        import docker

        if self._client is None:
            self._client = docker.from_env(timeout=None)
        return self._client

    def _open(self) -> None:
        import docker.errors

        client = self._docker()
        if self.sandbox_id:
            try:
                self._container = client.containers.get(self.sandbox_id)
            except docker.errors.NotFound as exc:
                raise SandboxExpired(f"docker container {self.sandbox_id} is gone") from exc
            if self._container.status != "running":
                self._container.start()
            return
        try:
            self._container = client.containers.run(
                self._image,
                ["sleep", "infinity"],
                detach=True,
                init=True,
                name=self._name,
                user=f"{os.getuid()}:{os.getgid()}",
                working_dir=self.workspace_dir,
                volumes={p: {"bind": p, "mode": "rw"} for p in self._mounts},
                environment={"GIT_TERMINAL_PROMPT": "0", "HOME": "/tmp"},
                nano_cpus=int(self._cpus * 1_000_000_000),
                mem_limit=f"{self._memory_mb}m",
                pids_limit=2048,
                labels={LABEL: "1"},
            )
        except docker.errors.DockerException as exc:
            raise SandboxError(f"docker create failed: {exc}") from exc
        self.sandbox_id = self._container.id

    def _exec(self, script, timeout, env) -> RawResult:
        import docker.errors

        api = self._docker().api
        try:
            exec_id = api.exec_create(
                self._container.id,
                ["bash", "-c", script],
                environment=env or None,
                user=f"{os.getuid()}:{os.getgid()}",
            )["Id"]
            stdout, stderr = api.exec_start(exec_id, demux=True)
            code = api.exec_inspect(exec_id)["ExitCode"]
        except docker.errors.DockerException as exc:
            raise SandboxError(f"docker exec failed: {exc}") from exc
        return RawResult(
            stdout=(stdout or b"").decode("utf-8", "replace"),
            stderr=(stderr or b"").decode("utf-8", "replace"),
            exit_code=code if code is not None else -1,
        )

    def close(self) -> None:
        if self._container is not None:
            try:
                self._container.remove(force=True)
            except Exception:
                pass
        if self._client is not None:
            self._client.close()
