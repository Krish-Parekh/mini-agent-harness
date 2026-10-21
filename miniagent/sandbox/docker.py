from __future__ import annotations

import logging
import os
import time

from miniagent.sandbox.base import SandboxError, SandboxExpired
from miniagent.sandbox.shell import RawResult, ShellSandbox

LABEL = "miniagent.sandbox"
CONVERSATION_LABEL = "miniagent.conversation"
NAME_PREFIX = "miniagent-"

_log = logging.getLogger(__name__)


def docker_problem(image: str) -> str | None:
    import docker
    import docker.errors

    try:
        client = docker.from_env(timeout=3)
    except docker.errors.DockerException:
        return "Docker is not running"
    try:
        client.ping()
        client.images.get(image)
    except docker.errors.ImageNotFound:
        return f"image {image} not found, build it with `docker build -t {image} sandbox/`"
    except Exception:
        return "Docker is not running"
    finally:
        client.close()
    return None


def conversation_containers() -> dict[str, str]:
    import docker

    client = docker.from_env(timeout=10)
    try:
        found: dict[str, str] = {}
        for container in client.containers.list(all=True, filters={"label": f"{LABEL}=1"}):
            cid = container.labels.get(CONVERSATION_LABEL)
            if not cid and container.name.startswith(NAME_PREFIX):
                cid = container.name.removeprefix(NAME_PREFIX)
            if cid:
                found[cid] = container.id
        return found
    finally:
        client.close()


def remove_containers(containers: dict[str, str]) -> None:
    import docker
    import docker.errors

    client = docker.from_env(timeout=30)
    try:
        for cid, container_id in containers.items():
            try:
                client.containers.get(container_id).remove(force=True)
            except docker.errors.NotFound:
                continue
            _log.info("docker container removed: conversation=%s container=%s", cid, container_id)
    finally:
        client.close()


class DockerSandbox(ShellSandbox):

    provider = "docker"

    def __init__(
        self,
        *,
        workspace_dir: str,
        image: str,
        mounts: dict[str, str],
        conversation_id: str | None = None,
        sandbox_id: str | None = None,
        name: str | None = None,
        cpus: float = 2,
        memory_mb: int = 4096,
    ) -> None:
        super().__init__(workspace_dir)
        self.sandbox_id = sandbox_id
        self._image = image
        self._mounts = mounts
        self._conversation_id = conversation_id
        self._name = name
        self._cpus = cpus
        self._memory_mb = memory_mb
        self._client = None
        self._container = None
        self._last_used = time.monotonic()

    def _docker(self):
        import docker

        if self._client is None:
            self._client = docker.from_env(timeout=None)
        return self._client

    def _labels(self) -> dict[str, str]:
        labels = {LABEL: "1"}
        if self._conversation_id:
            labels[CONVERSATION_LABEL] = self._conversation_id
        return labels

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
                _log.info(
                    "docker container started: conversation=%s container=%s",
                    self._conversation_id,
                    self.sandbox_id,
                )
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
                volumes={p: {"bind": p, "mode": mode} for p, mode in self._mounts.items()},
                environment={"GIT_TERMINAL_PROMPT": "0", "HOME": "/tmp"},
                nano_cpus=int(self._cpus * 1_000_000_000),
                mem_limit=f"{self._memory_mb}m",
                pids_limit=2048,
                labels=self._labels(),
            )
        except docker.errors.DockerException as exc:
            raise SandboxError(f"docker create failed: {exc}") from exc
        self.sandbox_id = self._container.id
        _log.info(
            "docker container created: conversation=%s container=%s",
            self._conversation_id,
            self.sandbox_id,
        )

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
        finally:
            self._last_used = time.monotonic()
        return RawResult(
            stdout=(stdout or b"").decode("utf-8", "replace"),
            stderr=(stderr or b"").decode("utf-8", "replace"),
            exit_code=code if code is not None else -1,
        )

    def stop_if_idle(self, idle_s: int) -> bool:
        import docker.errors

        with self._open_lock:
            with self._lock:
                busy = bool(self._inflight)
            if not self._opened or busy or time.monotonic() - self._last_used < idle_s:
                return False
            try:
                self._container.stop(timeout=5)
            except docker.errors.DockerException as exc:
                _log.warning("docker stop failed: conversation=%s: %s", self._conversation_id, exc)
                return False
            self._opened = False
        _log.info(
            "docker container stopped: conversation=%s container=%s",
            self._conversation_id,
            self.sandbox_id,
        )
        return True

    def close(self) -> None:
        if self._container is None and self.sandbox_id:
            try:
                self._container = self._docker().containers.get(self.sandbox_id)
            except Exception:
                pass
        if self._container is not None:
            try:
                self._container.remove(force=True)
                _log.info(
                    "docker container removed: conversation=%s container=%s",
                    self._conversation_id,
                    self.sandbox_id,
                )
            except Exception:
                pass
        if self._client is not None:
            self._client.close()
