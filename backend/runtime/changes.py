from __future__ import annotations

import shlex

from backend.schemas import ChangedFile, FileContent, FileDiff
from miniagent.sandbox.base import Sandbox

_STATUS = {"A": "added", "M": "modified", "D": "deleted"}
MAX_PATCH_CHARS = 200_000

_EXCLUDE_DIRS = ("node_modules", ".next", "dist", "build", ".venv", "__pycache__")
_EXCLUDE = " ".join(
    shlex.quote(f":(exclude,glob)**/{d}/**") for d in _EXCLUDE_DIRS
)


def _intent_to_add(sandbox: Sandbox) -> None:
    """Mark untracked files intent-to-add so they show up in `git diff HEAD`,
    skipping vendored dirs like node_modules."""
    sandbox.run_command(f"git add -A -N -- . {_EXCLUDE}")


def list_changes(sandbox: Sandbox, revs: str = "HEAD") -> list[ChangedFile]:
    _intent_to_add(sandbox)
    numstat = sandbox.run_command(f"git diff {revs} --numstat -- . {_EXCLUDE}").stdout
    name_status = sandbox.run_command(
        f"git diff {revs} --name-status -- . {_EXCLUDE}"
    ).stdout

    counts: dict[str, tuple[int, int]] = {}
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        adds, dels, path = parts[0], parts[1], parts[-1]
        counts[path] = (
            0 if adds == "-" else int(adds),
            0 if dels == "-" else int(dels),
        )

    changes: list[ChangedFile] = []
    for line in name_status.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        path = parts[-1]
        adds, dels = counts.get(path, (0, 0))
        changes.append(
            ChangedFile(
                path=path,
                additions=adds,
                deletions=dels,
                status=_STATUS.get(parts[0][0], "modified"),
            )
        )
    return changes


def file_diff(sandbox: Sandbox, path: str, revs: str = "HEAD") -> FileDiff:
    _intent_to_add(sandbox)
    patch = sandbox.run_command(f"git diff {revs} -- {shlex.quote(path)}").stdout
    if len(patch) <= MAX_PATCH_CHARS:
        return FileDiff(path=path, patch=patch)
    return FileDiff(path=path, patch=patch[:MAX_PATCH_CHARS], truncated=True)


def merge_base(sandbox: Sandbox, base: str) -> str:
    result = sandbox.run_command(f"git merge-base HEAD {shlex.quote(base)}")
    return result.stdout.strip() if result.exit_code == 0 else "HEAD"


def list_files(sandbox: Sandbox) -> list[str]:
    out = sandbox.run_command(
        f"git ls-files --cached --others --exclude-standard -- . {_EXCLUDE}"
    ).stdout
    return sorted(line for line in out.splitlines() if line)


def file_content(sandbox: Sandbox, path: str) -> FileContent:
    if path.startswith("/") or ".." in path.split("/"):
        return FileContent(path=path, content="")
    try:
        content = sandbox.read_file(path)
    except Exception:
        content = ""
    return FileContent(path=path, content=content)
