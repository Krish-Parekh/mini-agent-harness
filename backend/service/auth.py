from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx

from backend.core.jwt import Claims
from backend.models import GitHubConnectionRow, UserRow
from backend.repository import GitHubConnectionRepository, UserRepository
from backend.schemas import AuthState, GitHubConnection, UserOut

GITHUB_USER_URL = "https://api.github.com/user"


class AuthService:

    def __init__(
        self, users: UserRepository, connections: GitHubConnectionRepository
    ) -> None:
        self._users = users
        self._connections = connections

    async def sync(self, claims: Claims, provider_token: str | None) -> AuthState:
        user = await self._users.upsert(
            user_id=uuid.UUID(claims.sub),
            email=claims.email,
            avatar_url=claims.avatar_url,
        )
        connection = await self._connections.get(user.id)
        if provider_token:
            identity = await _fetch_github_identity(provider_token)
            if identity is not None:
                connection = await self._connections.upsert(
                    user_id=user.id,
                    github_user_id=identity.github_user_id,
                    login=identity.login,
                    avatar_url=identity.avatar_url,
                    access_token=provider_token,
                    scopes=identity.scopes,
                )
        return _state(user, connection)

    async def state(self, user: UserRow) -> AuthState:
        return _state(user, await self._connections.get(user.id))

    async def disconnect_github(self, user_id: uuid.UUID) -> bool:
        return await self._connections.delete(user_id)


@dataclass(frozen=True)
class _GitHubIdentity:
    github_user_id: int
    login: str
    avatar_url: str | None
    scopes: str | None


async def _fetch_github_identity(token: str) -> _GitHubIdentity | None:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                GITHUB_USER_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
            )
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    body = resp.json()
    login = body.get("login")
    github_user_id = body.get("id")
    if not isinstance(login, str) or not isinstance(github_user_id, int):
        return None
    return _GitHubIdentity(
        github_user_id=github_user_id,
        login=login,
        avatar_url=body.get("avatar_url"),
        scopes=resp.headers.get("x-oauth-scopes"),
    )


def _state(user: UserRow, connection: GitHubConnectionRow | None) -> AuthState:
    return AuthState(
        user=UserOut(
            id=str(user.id), email=user.email, avatar_url=user.avatar_url
        ),
        github=_connection_out(connection),
    )


def _connection_out(connection: GitHubConnectionRow | None) -> GitHubConnection:
    if connection is None:
        return GitHubConnection(connected=False)
    return GitHubConnection(
        connected=True,
        login=connection.login,
        avatar_url=connection.avatar_url,
        connected_at=connection.connected_at,
    )
