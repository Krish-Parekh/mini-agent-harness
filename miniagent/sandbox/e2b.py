from __future__ import annotations

from miniagent.sandbox.base import TIMEOUT_EXIT_CODE, SandboxError, SandboxExpired
from miniagent.sandbox.shell import RawResult, ShellSandbox


class E2BSandbox(ShellSandbox):
    provider = "e2b"

    def __init__(
        self,
        *,
        template: str | None = None,
        lifetime_s: int = 3600,
        sandbox_id: str | None = None,
        name: str | None = None,
        workspace_dir: str = "/home/user/workspace",
    ) -> None:
        super().__init__(workspace_dir)
        self.sandbox_id = sandbox_id
        self._template = template
        self._lifetime_s = lifetime_s
        self._name = name
        self._sbx = None

    def _open(self) -> None:
        import e2b

        try:
            if self.sandbox_id:
                self._sbx = e2b.Sandbox.connect(self.sandbox_id, timeout=self._lifetime_s)
            else:
                self._sbx = e2b.Sandbox.create(
                    template=self._template,
                    timeout=self._lifetime_s,
                    metadata={"app": "miniagent", "conversation": self._name or ""},
                    allow_internet_access=True,
                )
                self.sandbox_id = self._sbx.sandbox_id
                self._sbx.files.make_dir(self.workspace_dir)
        except (e2b.SandboxNotFoundException, e2b.NotFoundException) as exc:
            raise SandboxExpired(f"e2b sandbox {self.sandbox_id} is gone") from exc
        except e2b.SandboxException as exc:
            raise SandboxError(f"e2b sandbox setup failed: {exc}") from exc

    def _exec(self, script, timeout, env) -> RawResult:
        import e2b

        try:
            result = self._sbx.commands.run(script, envs=env or None, timeout=timeout)
        except e2b.CommandExitException as exc:
            return RawResult(stdout=exc.stdout, stderr=exc.stderr, exit_code=exc.exit_code)
        except e2b.TimeoutException as exc:
            return RawResult(stdout="", stderr=f"{exc}\n", exit_code=TIMEOUT_EXIT_CODE)
        except e2b.SandboxException as exc:
            raise SandboxError(f"e2b command failed: {exc}") from exc
        return RawResult(stdout=result.stdout, stderr=result.stderr, exit_code=result.exit_code)

    def write_file(self, path: str, content: str, workdir: str | None = None) -> None:
        self.ensure_open()
        self._sbx.files.write(self._abs(path, workdir), content)

    def read_file(self, path: str, workdir: str | None = None) -> str:
        import e2b

        self.ensure_open()
        try:
            return self._sbx.files.read(self._abs(path, workdir))
        except (e2b.FileNotFoundException, e2b.NotFoundException) as exc:
            raise FileNotFoundError(path) from exc

    def list_files(self, path: str, workdir: str | None = None) -> list[str]:
        import e2b

        self.ensure_open()
        try:
            entries = self._sbx.files.list(self._abs(path, workdir), depth=1)
        except (e2b.FileNotFoundException, e2b.NotFoundException):
            return []
        return sorted(entry.name for entry in entries)

    def extend(self, seconds: int) -> None:
        if self._sbx is not None:
            self._sbx.set_timeout(seconds)

    def close(self) -> None:
        import e2b

        try:
            if self._sbx is not None:
                self._sbx.kill()
            elif self.sandbox_id:
                e2b.Sandbox.kill(self.sandbox_id)
        except Exception:
            pass
