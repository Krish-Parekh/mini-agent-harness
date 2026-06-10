"""Open a GitHub pull request for a conversation's branch.

Two steps: commit + push the worktree's branch from the sandbox (git, blocking),
then create the PR through the GitHub REST API (httpx, async). The OAuth token is
only ever used to build an authenticated remote URL or as an API bearer — it never
reaches an event or the persisted log.
"""

from __future__ import annotations

import shlex

import httpx

from miniagent.sandbox.local import LocalSandbox
from miniagent.sandbox.workspace import (
    WorkspaceError,
    _redact,
    authenticated_git_url,
)

_API = "https://api.github.com"
_COMMITTER = (
    "-c user.name=miniagent "
    "-c user.email=miniagent@users.noreply.github.com"
)


def commit_and_push(
    sandbox: LocalSandbox, repo: str, branch: str, token: str | None, message: str
) -> None:
    """Stage everything, commit (no-op if clean), and force-push `branch` to origin.
    Blocking — call in a worker thread."""
    sandbox.run_command("git add -A")
    # A clean tree makes commit exit non-zero; that's fine — earlier commits on the
    # branch still get pushed. Real failures surface at the push step.
    sandbox.run_command(f"git {_COMMITTER} commit -m {shlex.quote(message)}")
    url = authenticated_git_url(repo, token)
    push = sandbox.run_command(
        f"git push --force {shlex.quote(url)} HEAD:{shlex.quote(branch)}", timeout=120
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
    """Open a PR via the GitHub API and return its JSON (includes number, html_url)."""
    owner, _, name = repo.partition("/")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
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
