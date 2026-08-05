from __future__ import annotations

from collections.abc import AsyncIterable

from fastapi.sse import ServerSentEvent

from backend.runtime.manager import ManagedConversation, StreamFrame
from backend.schemas import StatusUpdate


def _event_frame(event, seq: int | None) -> ServerSentEvent:
    return ServerSentEvent(
        raw_data=event.model_dump_json(),
        event=event.kind,
        id=str(seq) if seq is not None else None,
    )


def _status_frame(status: str) -> ServerSentEvent:
    return ServerSentEvent(
        raw_data=StatusUpdate(status=status).model_dump_json(),
        event="status",
    )


async def stream_conversation(
    managed: ManagedConversation, last_event_id: int | None
) -> AsyncIterable[ServerSentEvent]:
    queue = managed.broker.subscribe()
    try:
        replayed: set[str] = set()
        for seq, event in enumerate(list(managed.conversation.events), start=1):
            if last_event_id is not None and seq <= last_event_id:
                replayed.add(event.id)
                continue
            replayed.add(event.id)
            yield _event_frame(event, seq)
        yield _status_frame(managed.conversation.status.value)
        while True:
            item = await queue.get()
            if isinstance(item, StatusUpdate):
                yield _status_frame(item.status)
                continue
            if not isinstance(item, StreamFrame):
                continue
            if item.event.id in replayed:
                continue
            replayed.add(item.event.id)
            yield _event_frame(item.event, item.seq)
    finally:
        managed.broker.unsubscribe(queue)
