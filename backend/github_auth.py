from __future__ import annotations

import secrets

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from miniagent.config import Settings

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
API_USER_URL = "https://api.github.com/user"


class GitHubAuth:
    """Single-user, in-memory GitHub connection for v1. The token lives only in
    process memory and is never written to an event or the JSONL log."""

    def __init__(self) -> None:
        self.token: str | None = None
        self.login: str | None = None
        self._pending_states: set[str] = set()

    def new_state(self) -> str:
        state = secrets.token_urlsafe(16)
        self._pending_states.add(state)
        return state

    def consume_state(self, state: str) -> bool:
        return state in self._pending_states and (
            self._pending_states.discard(state) or True
        )


router = APIRouter(prefix="/auth/github")


def _auth(request: Request) -> GitHubAuth:
    return request.app.state.github


def _settings(request: Request) -> Settings:
    return request.app.state.settings


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
    return RedirectResponse(f"{settings.frontend_url}/repos?connected=1")


@router.get("/repos")
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
    return [
        {
            "full_name": r["full_name"],
            "name": r["name"],
            "private": r["private"],
            "default_branch": r["default_branch"],
            "description": r.get("description"),
            "updated_at": r["updated_at"],
        }
        for r in resp.json()
    ]


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
