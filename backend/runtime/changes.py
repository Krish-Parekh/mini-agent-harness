from __future__ import annotations

import base64
import shlex

from backend.schemas import ChangedFile, FileContent, FileDiff
from miniagent.sandbox.base import Sandbox

_STATUS = {"A": "added", "M": "modified", "D": "deleted"}
MAX_PATCH_CHARS = 200_000
MAX_PREVIEW_BYTES = 25 * 1024 * 1024
_MISSING_EXIT_CODE = 44
_TOO_LARGE_EXIT_CODE = 45

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


class PreviewTooLarge(Exception):
    pass


def _outside_checkout(path: str) -> bool:
    return path.startswith("/") or ".." in path.split("/")


def file_content(sandbox: Sandbox, path: str) -> FileContent:
    if _outside_checkout(path):
        return FileContent(path=path, content="")
    try:
        content = sandbox.read_file(path)
    except Exception:
        content = ""
    return FileContent(path=path, content=content)


def file_bytes(sandbox: Sandbox, path: str, rev: str | None = None) -> bytes:
    if _outside_checkout(path):
        raise FileNotFoundError(path)
    if rev:
        spec = shlex.quote(f"{rev}:{path}")
        size, read = f"git cat-file -s {spec}", f"git cat-file blob {spec}"
    else:
        target = shlex.quote(path)
        size, read = f"wc -c < {target}", f"cat {target}"
    result = sandbox.run_command(
        f"size=$({size} 2>/dev/null) || exit {_MISSING_EXIT_CODE}\n"
        f"[ $size -le {MAX_PREVIEW_BYTES} ] || exit {_TOO_LARGE_EXIT_CODE}\n"
        f"{read} | base64",
        timeout=120,
    )
    if result.exit_code == _TOO_LARGE_EXIT_CODE:
        raise PreviewTooLarge(path)
    if result.exit_code != 0:
        raise FileNotFoundError(path)
    return base64.b64decode("".join(result.stdout.split()))
