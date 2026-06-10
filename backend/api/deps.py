from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException
from starlette.requests import HTTPConnection

from backend.runtime.github import GitHubAuth
from backend.runtime.manager import ManagedConversation
from backend.service import ConversationService


def get_service(conn: HTTPConnection) -> ConversationService:
    return conn.app.state.service


def get_github(conn: HTTPConnection) -> GitHubAuth:
    return conn.app.state.github


ServiceDep = Annotated[ConversationService, Depends(get_service)]
GitHubDep = Annotated[GitHubAuth, Depends(get_github)]


async def require_conversation(cid: str, service: ServiceDep) -> ManagedConversation:
    """Resolve a conversation by id (reviving from storage if needed), 404 if absent.

    Used as a dependency so route handlers receive the live conversation directly
    and the not-found rule lives in one place.
    """
    managed = await service.get_or_revive(cid)
    if managed is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return managed


ManagedDep = Annotated[ManagedConversation, Depends(require_conversation)]
