from __future__ import annotations

import shlex

from miniagent.agent import SPILL_ROOT, exclude_from_git
from miniagent.sandbox.base import Sandbox
from miniagent.sandbox.workspace import COMMITTER

REF_PREFIX = "refs/miniagent/checkpoints"
_KEEP = shlex.quote(f":(exclude){SPILL_ROOT}")
_SNAPSHOT = (
    'tmp="$(mktemp)" && trap \'rm -f "$tmp"\' EXIT && '
    '{ cp -p "$(git rev-parse --git-path index)" "$tmp" 2>/dev/null || true; } && '
    'GIT_INDEX_FILE="$tmp" git add -A && '
    'tree="$(GIT_INDEX_FILE="$tmp" git write-tree)" && '
    'if git rev-parse -q --verify HEAD >/dev/null; '
    f'then git {COMMITTER} commit-tree "$tree" -p HEAD -m checkpoint; '
    f'else git {COMMITTER} commit-tree "$tree" -m checkpoint; fi'
)


class CheckpointError(Exception):
    pass


def ref(name: str) -> str:
    return f"{REF_PREFIX}/{name}"


def _git(sandbox: Sandbox, command: str) -> str:
    result = sandbox.run_command(command, timeout=60)
    if result.exit_code != 0:
        raise CheckpointError((result.stderr.strip() or result.stdout.strip())[:300])
    return result.stdout.strip()


def record(sandbox: Sandbox, name: str) -> None:
    exclude_from_git(sandbox)
    target = shlex.quote(ref(name))
    _git(
        sandbox,
        f"git rev-parse -q --verify {target} >/dev/null || "
        f'{{ oid="$({_SNAPSHOT})" && git update-ref {target} "$oid"; }}',
    )


def snapshot(sandbox: Sandbox) -> str:
    return _git(sandbox, _SNAPSHOT)


def names(sandbox: Sandbox) -> set[str]:
    command = f"git for-each-ref --format='%(refname:lstrip=3)' {REF_PREFIX}"
    return set(sandbox.run_command(command, timeout=30).stdout.split())


def exists(sandbox: Sandbox, name: str) -> bool:
    command = f"git rev-parse -q --verify {shlex.quote(ref(name))}"
    return sandbox.run_command(command, timeout=30).exit_code == 0


def restore(sandbox: Sandbox, name: str) -> None:
    source = shlex.quote(ref(name))
    _git(
        sandbox,
        f"git restore --source={source} --worktree --staged -- . {_KEEP} && "
        f"git clean -fdq -- . {_KEEP} && git reset -q",
    )


def drop(sandbox: Sandbox, names: list[str]) -> None:
    if names:
        _git(
            sandbox,
            " && ".join(f"git update-ref -d {shlex.quote(ref(name))}" for name in names),
        )
