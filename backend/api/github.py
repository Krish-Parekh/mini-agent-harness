from __future__ import annotations

import re

import httpx
from fastapi import APIRouter, HTTPException

from backend.api.deps import RequiredGitHub
from backend.schemas import ImportRepoRequest, RepoOut
from backend.schemas.conversation import BranchOut

GITHUB_API = "https://api.github.com"

router = APIRouter(prefix="/auth/github")


def _to_repo_out(r: dict) -> RepoOut:
    return RepoOut(
        full_name=r["full_name"],
        name=r["name"],
        owner=r["owner"]["login"],
        private=r["private"],
        default_branch=r["default_branch"],
        description=r.get("description"),
        language=r.get("language"),
        updated_at=r["updated_at"],
    )


def _parse_repo(raw: str) -> tuple[str, str]:
    s = re.sub(r"^https?://github\.com/", "", raw.strip())
    s = re.sub(r"\.git$", "", s).strip("/")
    parts = s.split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise HTTPException(
            status_code=400, detail="expected a GitHub URL or owner/name"
        )
    return parts[0], parts[1]


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }


@router.get("/repos", response_model=list[RepoOut])
async def github_repos(gh: RequiredGitHub):
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GITHUB_API}/user/repos",
            headers=_headers(gh.token),
            params={"per_page": 100, "sort": "updated"},
        )
    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="GitHub token was revoked")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="failed to list repositories")
    return [_to_repo_out(r) for r in resp.json()]


@router.get("/repos/{owner}/{name}/branches", response_model=list[BranchOut])
async def github_branches(owner: str, name: str, gh: RequiredGitHub):
    async with httpx.AsyncClient(timeout=15) as client:
        repo = await client.get(
            f"{GITHUB_API}/repos/{owner}/{name}", headers=_headers(gh.token)
        )
        if repo.status_code == 401:
            raise HTTPException(status_code=401, detail="GitHub token was revoked")
        if repo.status_code != 200:
            raise HTTPException(status_code=404, detail="repository not found")
        branches = await client.get(
            f"{GITHUB_API}/repos/{owner}/{name}/branches",
            headers=_headers(gh.token),
            params={"per_page": 100},
        )
    if branches.status_code != 200:
        raise HTTPException(status_code=502, detail="failed to list branches")
    default = repo.json()["default_branch"]
    names = sorted({b["name"] for b in branches.json()} | {default})
    ordered = [default] + [n for n in names if n != default]
    return [BranchOut(name=n, default=n == default) for n in ordered]


@router.post("/import", response_model=RepoOut)
async def github_import(body: ImportRepoRequest, gh: RequiredGitHub):
    owner, name = _parse_repo(body.repo)
    async with httpx.AsyncClient(timeout=30) as client:
        if owner.lower() == gh.login.lower():
            resp = await client.get(
                f"{GITHUB_API}/repos/{owner}/{name}", headers=_headers(gh.token)
            )
        else:
            resp = await client.post(
                f"{GITHUB_API}/repos/{owner}/{name}/forks", headers=_headers(gh.token)
            )
    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="GitHub token was revoked")
    if resp.status_code == 404:
        raise HTTPException(
            status_code=404, detail="repository not found or not accessible"
        )
    if resp.status_code not in (200, 201, 202):
        raise HTTPException(status_code=502, detail="failed to import repository")
    return _to_repo_out(resp.json())
