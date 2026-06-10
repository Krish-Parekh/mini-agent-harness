from __future__ import annotations

from fastapi import WebSocket, WebSocketDisconnect

from backend.runtime.manager import ManagedConversation
from backend.schemas import StatusUpdate


async def stream_conversation(
    websocket: WebSocket, managed: ManagedConversation
) -> None:
    """Replay a conversation's event history to the socket, then stream the live tail.

    Subscribe before snapshotting so no event slips through the gap between the
    snapshot and the first live read; dedupe the overlap by id while draining the
    queue. Always unsubscribes on exit so a dropped client doesn't leak a queue.
    """
    queue = managed.broker.subscribe()
    await websocket.accept()
    try:
        replayed: set[str] = set()
        for event in list(managed.conversation.events):
            replayed.add(event.id)
            await websocket.send_text(event.model_dump_json())
        # Seed current status so the client starts correct without polling.
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
