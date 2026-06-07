from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from starlette.requests import HTTPConnection

from backend.runtime.github import GitHubAuth
from backend.service import ConversationService


def get_service(conn: HTTPConnection) -> ConversationService:
    return conn.app.state.service


def get_github(conn: HTTPConnection) -> GitHubAuth:
    return conn.app.state.github


ServiceDep = Annotated[ConversationService, Depends(get_service)]
GitHubDep = Annotated[GitHubAuth, Depends(get_github)]
