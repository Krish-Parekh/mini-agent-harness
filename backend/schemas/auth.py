from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SyncRequest(BaseModel):

    provider_token: str | None = None


class UserOut(BaseModel):
    id: str
    email: str | None = None
    avatar_url: str | None = None


class GitHubConnection(BaseModel):

    connected: bool
    login: str | None = None
    avatar_url: str | None = None
    connected_at: datetime | None = None


class AuthState(BaseModel):
    user: UserOut
    github: GitHubConnection
