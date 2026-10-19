from __future__ import annotations

import shlex

from miniagent.sandbox.base import Sandbox

GIT_TOKEN_ENV = "MINIAGENT_GIT_TOKEN"
COMMITTER = "-c user.name=miniagent -c user.email=miniagent@users.noreply.github.com"
# The empty helper first clears any helper from git config (osxkeychain, a
# store file), so the token only ever comes from this one command's env.
_CREDENTIAL_HELPER = (
    "-c credential.helper= "
    "-c credential.helper="
    + shlex.quote(
        f'!f() {{ echo username=x-access-token; echo "password=${GIT_TOKEN_ENV}"; }}; f'
    )
)


class WorkspaceError(Exception):
    pass


def git_url(repo: str) -> str:
    return f"https://github.com/{repo}.git"


def git_auth(token: str | None) -> tuple[str, dict[str, str] | None]:
    """git options and per-command env that authenticate to GitHub without
    putting the token in argv, a URL, or .git/config."""
    if not token:
        return "", None
    return _CREDENTIAL_HELPER, {GIT_TOKEN_ENV: token}


def _redact(text: str, token: str | None) -> str:
    return text.replace(token, "***") if token else text


def clone_repo(
    sandbox: Sandbox,
    repo: str,
    branch: str | None,
    token: str | None,
    work_branch: str,
) -> None:
    """Clone `owner/name` into the sandbox working directory and check out the
    Conversation's own branch. Runs outside the agent loop."""
    auth, env = git_auth(token)
    branch_arg = f"--branch {shlex.quote(branch)} " if branch else ""
    result = sandbox.run_command(
        f"git {auth} clone --quiet {branch_arg}{shlex.quote(git_url(repo))} .",
        timeout=300,
        env=env,
    )
    if result.exit_code != 0:
        raise WorkspaceError(_redact(result.stderr, token) or "git clone failed")
    checkout = sandbox.run_command(
        f"git checkout --quiet -B {shlex.quote(work_branch)}", timeout=60
    )
    if checkout.exit_code != 0:
        raise WorkspaceError(_redact(checkout.stderr, token) or "git checkout failed")
