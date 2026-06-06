from __future__ import annotations

import shlex

from miniagent.sandbox.base import Sandbox


class WorkspaceError(Exception):
    pass


def authenticated_git_url(repo: str, token: str | None) -> str:
    if token:
        return f"https://x-access-token:{token}@github.com/{repo}.git"
    return f"https://github.com/{repo}.git"


def _redact(text: str, token: str | None) -> str:
    return text.replace(token, "***") if token else text


def clone_repo(
    sandbox: Sandbox, repo: str, branch: str | None, token: str | None
) -> None:
    """Clone `owner/name` into the sandbox working directory. Runs outside the
    agent loop, so the token-bearing URL never reaches an event or the log."""
    url = authenticated_git_url(repo, token)
    result = sandbox.run_command(f"git clone {shlex.quote(url)} .", timeout=300)
    if result.exit_code != 0:
        raise WorkspaceError(_redact(result.stderr, token) or "git clone failed")
    if branch:
        checkout = sandbox.run_command(f"git checkout {shlex.quote(branch)}", timeout=60)
        if checkout.exit_code != 0:
            raise WorkspaceError(_redact(checkout.stderr, token) or "git checkout failed")
