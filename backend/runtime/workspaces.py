from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import threading
from pathlib import Path

from miniagent.sandbox.workspace import (
    BRANCH_PREFIX,
    WorkspaceError,
    _redact,
    git_auth,
    git_url,
)


class WorkspaceManager:

    def __init__(self, data_dir: Path) -> None:
        base = data_dir.resolve()
        self._repos_dir = base / "repos"
        self._checkouts_dir = base / "worktrees"
        self._repos_dir.mkdir(parents=True, exist_ok=True)
        self._checkouts_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def checkout_dir(self, cid: str) -> Path:
        return self._checkouts_dir / cid

    def _clone_dir(self, repo: str) -> Path:
        owner, _, name = repo.partition("/")
        return self._repos_dir / owner / name

    def _repo_lock(self, repo: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(repo, threading.Lock())

    def mounts(self, cid: str, repo: str | None) -> dict[str, str]:
        mounts = {str(self.checkout_dir(cid)): "rw"}
        if repo:
            mounts[str(self._clone_dir(repo) / ".git" / "objects")] = "ro"
        return mounts

    def empty_checkout(self, cid: str) -> str:
        checkout = self.checkout_dir(cid)
        checkout.mkdir(parents=True, exist_ok=True)
        return str(checkout)

    def prepare(
        self, cid: str, repo: str, branch: str | None, token: str | None
    ) -> str:
        clone_dir = self._clone_dir(repo)
        checkout = self.checkout_dir(cid)
        with self._repo_lock(repo):
            if not (clone_dir / ".git").exists():
                self._clone(repo, branch, token, clone_dir)
            else:
                self._fetch(token, clone_dir)
            self._git(clone_dir, ["config", "gc.auto", "0"], token=None, timeout=30)
            self._git(clone_dir, ["config", "maintenance.auto", "false"], token=None, timeout=30)
            ref = f"origin/{branch}" if branch else "origin/HEAD"
            base = self._git(
                clone_dir, ["rev-parse", "--verify", f"{ref}^{{commit}}"], token=None, timeout=30
            ).strip()
        checkout.mkdir(parents=True, exist_ok=True)
        for child in checkout.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        self._git(
            None,
            ["clone", "--quiet", "--shared", "--no-checkout", str(clone_dir), str(checkout)],
            token=None,
            timeout=120,
        )
        self._git(checkout, ["remote", "set-url", "origin", git_url(repo)], token=None, timeout=30)
        self._git(
            checkout,
            ["fetch", "--quiet", "--no-tags", str(clone_dir),
             "+refs/remotes/origin/*:refs/remotes/origin/*"],
            token=None,
            timeout=120,
        )
        self._git(
            checkout,
            ["checkout", "--quiet", "-B", f"{BRANCH_PREFIX}/{cid}", base],
            token=None,
            timeout=120,
        )
        return str(checkout)

    def release(self, cid: str, repo: str | None) -> None:
        checkout = self.checkout_dir(cid)
        if not checkout.exists():
            return
        if repo is not None and (checkout / ".git").is_file():
            clone_dir = self._clone_dir(repo)
            with self._repo_lock(repo):
                self._git(clone_dir, ["worktree", "remove", "--force", str(checkout)],
                          token=None, timeout=60, check=False)
                self._git(clone_dir, ["branch", "-D", f"{BRANCH_PREFIX}/{cid}"],
                          token=None, timeout=30, check=False)
        shutil.rmtree(checkout, ignore_errors=True)

    def _clone(
        self, repo: str, branch: str | None, token: str | None, clone_dir: Path
    ) -> None:
        clone_dir.parent.mkdir(parents=True, exist_ok=True)
        auth, env = git_auth(token)
        args = [*shlex.split(auth), "clone"]
        if branch:
            args += ["--branch", branch]
        args += [git_url(repo), str(clone_dir)]
        self._git(None, args, token=token, timeout=300, env=env)

    def _fetch(self, token: str | None, clone_dir: Path) -> None:
        auth, env = git_auth(token)
        args = [*shlex.split(auth), "fetch", "--quiet", "--prune", "origin"]
        self._git(clone_dir, args, token=token, timeout=300, env=env)

    def _git(
        self,
        cwd: Path | None,
        args: list[str],
        *,
        token: str | None,
        timeout: int,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> str:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, **env} if env else None,
            )
        except subprocess.TimeoutExpired:
            if check:
                raise WorkspaceError(f"git {args[0]} timed out")
            return ""
        if check and proc.returncode != 0:
            raise WorkspaceError(
                _redact(proc.stderr.strip(), token) or f"git {args[0]} failed"
            )
        return proc.stdout
