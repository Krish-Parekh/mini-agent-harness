from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from miniagent.sandbox.workspace import (
    WorkspaceError,
    _redact,
    authenticated_git_url,
)

BRANCH_PREFIX = "miniagent"


class WorkspaceManager:
    """Clones each repo once, then gives every conversation an isolated git
    worktree + branch off that shared clone.

    Worktrees share the clone's object store, so per-conversation setup is a
    local checkout rather than a fresh network clone — fast start, and each
    conversation gets its own branch so concurrent chats never stomp each other.
    """

    def __init__(self, data_dir: Path) -> None:
        # Resolve to absolute: git worktree paths are passed to `git -C <clone>`,
        # which would otherwise resolve a relative path against the clone dir.
        base = data_dir.resolve()
        self._repos_dir = base / "repos"
        self._worktrees_dir = base / "worktrees"
        self._repos_dir.mkdir(parents=True, exist_ok=True)
        self._worktrees_dir.mkdir(parents=True, exist_ok=True)
        # One lock per repo so two conversations on the same repo can't race the
        # initial clone or concurrent worktree mutations.
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # --- paths -------------------------------------------------------------

    def worktree_dir(self, cid: str) -> Path:
        return self._worktrees_dir / cid

    def _clone_dir(self, repo: str) -> Path:
        owner, _, name = repo.partition("/")
        return self._repos_dir / owner / name

    def _repo_lock(self, repo: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(repo, threading.Lock())

    # --- lifecycle ---------------------------------------------------------

    def prepare(
        self, cid: str, repo: str, branch: str | None, token: str | None
    ) -> str:
        """Ensure `repo` is cloned once, then add this conversation's worktree.
        Returns the worktree path the sandbox should work in. Runs in a worker
        thread; thread-safe per repo."""
        clone_dir = self._clone_dir(repo)
        worktree = self.worktree_dir(cid)
        with self._repo_lock(repo):
            if not (clone_dir / ".git").exists():
                self._clone(repo, branch, token, clone_dir)
            base = f"origin/{branch}" if branch else "HEAD"
            self._git(
                clone_dir,
                ["worktree", "add", "--force", "-B", f"{BRANCH_PREFIX}/{cid}",
                 str(worktree), base],
                token=None,
                timeout=120,
            )
        return str(worktree)

    def release(self, cid: str, repo: str | None) -> None:
        """Best-effort teardown of a conversation's worktree + branch. The
        shared clone is left intact for other conversations on the same repo."""
        worktree = self.worktree_dir(cid)
        if repo is None or not worktree.exists():
            return
        clone_dir = self._clone_dir(repo)
        with self._repo_lock(repo):
            self._git(clone_dir, ["worktree", "remove", "--force", str(worktree)],
                      token=None, timeout=60, check=False)
            self._git(clone_dir, ["branch", "-D", f"{BRANCH_PREFIX}/{cid}"],
                      token=None, timeout=30, check=False)

    # --- git ---------------------------------------------------------------

    def _clone(
        self, repo: str, branch: str | None, token: str | None, clone_dir: Path
    ) -> None:
        clone_dir.parent.mkdir(parents=True, exist_ok=True)
        url = authenticated_git_url(repo, token)
        args = ["clone"]
        if branch:
            args += ["--branch", branch]
        args += [url, str(clone_dir)]
        self._git(None, args, token=token, timeout=300)
        # Drop the token-bearing remote so the secret isn't persisted on disk.
        self._git(
            clone_dir,
            ["remote", "set-url", "origin", f"https://github.com/{repo}.git"],
            token=token,
            timeout=30,
            check=False,
        )

    def _git(
        self,
        cwd: Path | None,
        args: list[str],
        *,
        token: str | None,
        timeout: int,
        check: bool = True,
    ) -> None:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            if check:
                raise WorkspaceError(f"git {args[0]} timed out")
            return
        if check and proc.returncode != 0:
            raise WorkspaceError(
                _redact(proc.stderr.strip(), token) or f"git {args[0]} failed"
            )
