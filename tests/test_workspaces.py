from __future__ import annotations

import subprocess

from backend.runtime import workspaces
from backend.runtime.workspaces import WorkspaceManager


def _git(cwd, *args) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(seed, message: str) -> str:
    _git(seed, "commit", "-q", "--allow-empty", "-m", message)
    return _git(seed, "rev-parse", "HEAD")


def test_cached_clone_picks_up_commits_and_branches_pushed_later(tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    _git(tmp_path, "init", "-q", "-b", "main", str(seed))
    _commit(seed, "first")
    _git(seed, "push", "-q", str(remote), "main")
    monkeypatch.setattr(workspaces, "git_url", lambda repo: str(remote))
    manager = WorkspaceManager(tmp_path / "data")
    manager.prepare("c1", "octo/repo", None, None)

    latest = _commit(seed, "second")
    _git(seed, "push", "-q", str(remote), "main", "main:feature")

    default = manager.prepare("c2", "octo/repo", None, None)
    feature = manager.prepare("c3", "octo/repo", "feature", None)
    assert _git(default, "rev-parse", "HEAD") == latest
    assert _git(feature, "rev-parse", "HEAD") == latest


def test_prepare_keeps_an_existing_checkout_dir_so_container_mounts_stay_valid(tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    _git(tmp_path, "init", "-q", "-b", "main", str(seed))
    _commit(seed, "first")
    _git(seed, "push", "-q", str(remote), "main")
    monkeypatch.setattr(workspaces, "git_url", lambda repo: str(remote))
    manager = WorkspaceManager(tmp_path / "data")
    mounted = manager.checkout_dir("c1")
    mounted.mkdir(parents=True)
    (mounted / "stale.txt").write_text("left over")
    inode = mounted.stat().st_ino

    checkout = manager.prepare("c1", "octo/repo", None, None)

    assert mounted.stat().st_ino == inode
    assert not (mounted / "stale.txt").exists()
    assert _git(checkout, "rev-parse", "--abbrev-ref", "HEAD") == "miniagent/c1"
