from __future__ import annotations

import re

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from backend.runtime.github import GitHubAuth
from backend.schemas import ImportRepoRequest, RepoOut
from miniagent.config import Settings

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
API_USER_URL = "https://api.github.com/user"
GITHUB_API = "https://api.github.com"


router = APIRouter(prefix="/auth/github")


def _auth(request: Request) -> GitHubAuth:
    return request.app.state.github


def _settings(request: Request) -> Settings:
    return request.app.state.settings


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
    """Accept either a GitHub URL or 'owner/name' and return (owner, name)."""
    s = re.sub(r"^https?://github\.com/", "", raw.strip())
    s = re.sub(r"\.git$", "", s).strip("/")
    parts = s.split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise HTTPException(
            status_code=400, detail="expected a GitHub URL or owner/name"
        )
    return parts[0], parts[1]


def _redirect_uri(settings: Settings) -> str:
    return f"{settings.public_base_url}/auth/github/callback"


@router.get("/login")
async def github_login(request: Request):
    settings = _settings(request)
    if not settings.github_client_id:
        raise HTTPException(status_code=500, detail="GITHUB_CLIENT_ID not configured")
    state = _auth(request).new_state()
    url = (
        f"{AUTHORIZE_URL}?client_id={settings.github_client_id}"
        f"&redirect_uri={_redirect_uri(settings)}&scope=repo&state={state}"
    )
    return RedirectResponse(url)


@router.get("/callback")
async def github_callback(request: Request, code: str, state: str):
    auth = _auth(request)
    settings = _settings(request)
    if not auth.consume_state(state):
        raise HTTPException(status_code=400, detail="invalid or expired state")

    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.post(
            TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": _redirect_uri(settings),
            },
        )
        token = token_resp.json().get("access_token")
        if not token:
            raise HTTPException(status_code=400, detail="token exchange failed")

        user_resp = await client.get(
            API_USER_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
        )
        login = user_resp.json().get("login")

    auth.token = token
    auth.login = login
    return RedirectResponse(f"{settings.frontend_url}/?connected=1")


@router.get("/repos", response_model=list[RepoOut])
async def github_repos(request: Request):
    auth = _auth(request)
    if not auth.token:
        raise HTTPException(status_code=401, detail="not connected to github")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://api.github.com/user/repos",
            headers={
                "Authorization": f"Bearer {auth.token}",
                "Accept": "application/vnd.github+json",
            },
            params={"per_page": 100, "sort": "updated"},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="failed to list repositories")
    return [_to_repo_out(r) for r in resp.json()]


@router.post("/import", response_model=RepoOut)
async def github_import(request: Request, body: ImportRepoRequest):
    auth = _auth(request)
    if not auth.token:
        raise HTTPException(status_code=401, detail="not connected to github")
    owner, name = _parse_repo(body.repo)
    headers = {
        "Authorization": f"Bearer {auth.token}",
        "Accept": "application/vnd.github+json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        if auth.login and owner.lower() == auth.login.lower():
            # Already in the user's account — no fork required, just resolve it.
            resp = await client.get(f"{GITHUB_API}/repos/{owner}/{name}", headers=headers)
        else:
            # Fork creates (or returns the existing) copy under the user's account.
            resp = await client.post(
                f"{GITHUB_API}/repos/{owner}/{name}/forks", headers=headers
            )
    if resp.status_code == 404:
        raise HTTPException(
            status_code=404, detail="repository not found or not accessible"
        )
    if resp.status_code not in (200, 201, 202):
        raise HTTPException(status_code=502, detail="failed to import repository")
    return _to_repo_out(resp.json())


@router.get("/status")
async def github_status(request: Request):
    auth = _auth(request)
    return {"connected": auth.token is not None, "login": auth.login}


@router.post("/logout")
async def github_logout(request: Request):
    auth = _auth(request)
    auth.token = None
    auth.login = None
    return {"connected": False}
