from __future__ import annotations

from pathlib import Path
import subprocess

from miniagent.sandbox.base import Sandbox, CommandResult


class LocalSandbox(Sandbox):
    
    def __init__(self, workspace_dir: str | None = None): 
        self.workspace_dir = str(Path(workspace_dir or Path.cwd()).resolve())
        Path(self.workspace_dir).mkdir(parents=True, exist_ok=True)
    
    def _resolve(self, path: str) -> str:
        p = Path(path)
        if p.is_absolute():
            return str(p)
        return str(Path(self.workspace_dir).joinpath(p))
    
    def run_command(self, command: str, timeout: int = 30) -> CommandResult:
        try:
            process = subprocess.run(
                command,
                shell=True,
                cwd=self.workspace_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return CommandResult(
                stdout=process.stdout,
                stderr=process.stderr,
                exit_code=process.returncode,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                stdout="",
                stderr="Command timed out",
                exit_code=1,
            )
    
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