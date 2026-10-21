"""Open a GitHub pull request for a conversation's branch.

Two steps: commit + push the worktree's branch from the sandbox (git, blocking),
then create the PR through the GitHub REST API (httpx, async). The OAuth token
reaches git only through a per-command credential helper env, and the API only as a
bearer. It never reaches argv, an event, or the persisted log.
"""

from __future__ import annotations

import shlex

import httpx

from miniagent.sandbox.base import Sandbox
from miniagent.sandbox.workspace import (
    COMMITTER,
    WorkspaceError,
    _redact,
    git_auth,
    git_url,
)

_API = "https://api.github.com"
_TEMPLATE_PATHS = (
    ".github/pull_request_template.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "docs/pull_request_template.md",
    "PULL_REQUEST_TEMPLATE.md",
    "pull_request_template.md",
)
_MAX_DIFF_CHARS = 12_000


def staged_diff(sandbox: Sandbox) -> str:
    sandbox.run_command("git add -A")
    stat = sandbox.run_command("git diff --cached --stat").stdout
    patch = sandbox.run_command("git diff --cached").stdout
    return f"{stat}\n{patch[:_MAX_DIFF_CHARS]}".strip()


def pr_template(sandbox: Sandbox) -> str | None:
    for path in _TEMPLATE_PATHS:
        try:
            return sandbox.read_file(path)
        except Exception:
            continue
    return None


def commit_and_push(
    sandbox: Sandbox, repo: str, branch: str, token: str | None, message: str
) -> None:
    """Stage everything, commit (no-op if clean), and force-push `branch` to origin.
    Blocking; call in a worker thread."""
    sandbox.run_command("git add -A")
    # A clean tree makes commit exit non-zero; that's fine: earlier commits on the
    # branch still get pushed. Real failures surface at the push step.
    sandbox.run_command(f"git {COMMITTER} commit -m {shlex.quote(message)}")
    auth, env = git_auth(token)
    push = sandbox.run_command(
        f"git {auth} push --force {shlex.quote(git_url(repo))} HEAD:{shlex.quote(branch)}",
        timeout=120,
        env=env,
    )
    if push.exit_code != 0:
        raise WorkspaceError(_redact(push.stderr, token) or "git push failed")


async def create_pull_request(
    repo: str,
    head_branch: str,
    base_branch: str | None,
    token: str,
    title: str,
    body: str,
) -> dict:
    """Return the branch's open PR, or open one via the GitHub API (JSON includes
    number, html_url)."""
    owner, _, name = repo.partition("/")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        existing = await client.get(
            f"{_API}/repos/{owner}/{name}/pulls",
            headers=headers,
            params={"head": f"{owner}:{head_branch}", "state": "open"},
        )
        if existing.status_code < 300 and existing.json():
            return existing.json()[0]
        base = base_branch or await _default_branch(client, owner, name, headers)
        resp = await client.post(
            f"{_API}/repos/{owner}/{name}/pulls",
            headers=headers,
            json={"title": title, "head": head_branch, "base": base, "body": body},
        )
    if resp.status_code >= 300:
        raise WorkspaceError(
            f"GitHub PR creation failed ({resp.status_code}): {resp.text[:300]}"
        )
    return resp.json()


async def _default_branch(
    client: httpx.AsyncClient, owner: str, name: str, headers: dict
) -> str:
    resp = await client.get(f"{_API}/repos/{owner}/{name}", headers=headers)
    if resp.status_code >= 300:
        raise WorkspaceError(f"could not resolve default branch ({resp.status_code})")
    return resp.json()["default_branch"]
