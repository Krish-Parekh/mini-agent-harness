from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.requests import HTTPConnection

from backend.core.jwt import Claims, InvalidToken, TokenVerifier
from backend.models import UserRow
from backend.repository import GitHubConnectionRepository, UserRepository
from backend.runtime.manager import ManagedConversation
from backend.service import AuthService, ConversationService

_UNAUTHENTICATED = HTTPException(
    status_code=401,
    detail="not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)

bearer_scheme = HTTPBearer(auto_error=False)


def get_service(conn: HTTPConnection) -> ConversationService:
    return conn.app.state.service


def get_auth_service(conn: HTTPConnection) -> AuthService:
    return conn.app.state.auth_service


def get_verifier(conn: HTTPConnection) -> TokenVerifier:
    return conn.app.state.verifier


def get_connections(conn: HTTPConnection) -> GitHubConnectionRepository:
    return conn.app.state.connections


def get_users(conn: HTTPConnection) -> UserRepository:
    return conn.app.state.users


ServiceDep = Annotated[ConversationService, Depends(get_service)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
VerifierDep = Annotated[TokenVerifier, Depends(get_verifier)]
ConnectionsDep = Annotated[GitHubConnectionRepository, Depends(get_connections)]
UsersDep = Annotated[UserRepository, Depends(get_users)]


def verify_bearer(
    verifier: VerifierDep,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
) -> Claims:
    if credentials is None:
        raise _UNAUTHENTICATED
    try:
        return verifier.verify(credentials.credentials)
    except InvalidToken:
        raise _UNAUTHENTICATED from None


ClaimsDep = Annotated[Claims, Depends(verify_bearer)]


async def require_user(claims: ClaimsDep, users: UsersDep) -> UserRow:
    user = await users.get(_as_uuid(claims.sub))
    if user is None:
        raise _UNAUTHENTICATED
    return user


CurrentUser = Annotated[UserRow, Depends(require_user)]


@dataclass(frozen=True)
class CallerGitHub:
    token: str
    login: str


async def caller_github_token(
    user: CurrentUser, connections: ConnectionsDep
) -> str | None:
    return await connections.token_for(user.id)


CallerGitHubToken = Annotated[str | None, Depends(caller_github_token)]


async def require_github(
    user: CurrentUser, connections: ConnectionsDep
) -> CallerGitHub:
    connection = await connections.get(user.id)
    if connection is None:
        raise HTTPException(status_code=401, detail="GitHub is not connected")
    return CallerGitHub(token=connection.access_token, login=connection.login)


RequiredGitHub = Annotated[CallerGitHub, Depends(require_github)]


async def require_conversation(
    cid: str, service: ServiceDep, user: CurrentUser
) -> ManagedConversation:
    managed = await service.get_or_revive(cid, user.id)
    if managed is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return managed


ManagedDep = Annotated[ManagedConversation, Depends(require_conversation)]


def _as_uuid(sub: str) -> uuid.UUID:
    try:
        return uuid.UUID(sub)
    except ValueError:
        raise _UNAUTHENTICATED from None
