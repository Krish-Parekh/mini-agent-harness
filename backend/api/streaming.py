from __future__ import annotations

import uuid

from fastapi import WebSocket, WebSocketDisconnect

from backend.core.jwt import InvalidToken
from backend.models import UserRow
from backend.runtime.manager import ManagedConversation
from backend.schemas import StatusUpdate

_SUBPROTOCOL = "bearer"


async def authenticate_socket(websocket: WebSocket) -> UserRow | None:
    token = _subprotocol_token(websocket)
    await websocket.accept(subprotocol=_SUBPROTOCOL if token else None)
    if token is None:
        await websocket.close(code=4401)
        return None
    try:
        claims = websocket.app.state.verifier.verify(token)
        user = await websocket.app.state.users.get(uuid.UUID(claims.sub))
    except (InvalidToken, ValueError):
        user = None
    if user is None:
        await websocket.close(code=4401)
        return None
    return user


def _subprotocol_token(websocket: WebSocket) -> str | None:
    protocols = websocket.scope.get("subprotocols") or []
    if len(protocols) < 2 or protocols[0] != _SUBPROTOCOL:
        return None
    return protocols[1] or None


async def stream_conversation(
    websocket: WebSocket, managed: ManagedConversation
) -> None:
    queue = managed.broker.subscribe()
    try:
        replayed: set[str] = set()
        for event in list(managed.conversation.events):
            replayed.add(event.id)
            await websocket.send_text(event.model_dump_json())
        await websocket.send_text(
            StatusUpdate(status=managed.conversation.status.value).model_dump_json()
        )
        while True:
            event = await queue.get()
            if event.id in replayed:
                continue
            await websocket.send_text(event.model_dump_json())
    except WebSocketDisconnect:
        pass
    finally:
        managed.broker.unsubscribe(queue)
