from __future__ import annotations

from functools import partial

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from backend.manager import ConversationManager, ManagedConversation
from backend.schemas import (
    ConfirmRequest,
    ConversationInfo,
    CreateConversationRequest,
    SendMessageRequest,
)
from miniagent.conversation import Status

router = APIRouter()


def _manager(request: Request) -> ConversationManager:
    return request.app.state.manager


def _require(manager: ConversationManager, cid: str) -> ManagedConversation:
    managed = manager.get(cid)
    if managed is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return managed


def _info(managed: ManagedConversation) -> ConversationInfo:
    conv = managed.conversation
    return ConversationInfo(
        id=conv.id,
        status=conv.status.value,
        workspace_dir=managed.sandbox.workspace_dir,
        num_events=len(conv.events),
        repo=managed.repo,
        branch=managed.branch,
    )


@router.post("/conversations", response_model=ConversationInfo)
async def create_conversation(body: CreateConversationRequest, request: Request):
    manager = _manager(request)
    token = request.app.state.github.token
    managed = manager.create(
        repo=body.repo,
        branch=body.branch,
        workspace_dir=body.workspace_dir,
        confirm_mode=body.confirm_mode,
        token=token,
    )
    if body.repo or body.initial_message:
        manager.start(managed, body.initial_message)
    return _info(managed)


@router.get("/conversations", response_model=list[ConversationInfo])
async def list_conversations(request: Request):
    return [_info(m) for m in _manager(request).list()]


@router.get("/conversations/{cid}", response_model=ConversationInfo)
async def get_conversation(cid: str, request: Request):
    return _info(_require(_manager(request), cid))


@router.get("/conversations/{cid}/events")
async def get_events(cid: str, request: Request):
    managed = _require(_manager(request), cid)
    return [event.model_dump() for event in managed.conversation.events]


@router.post("/conversations/{cid}/messages", response_model=ConversationInfo)
async def send_message(cid: str, body: SendMessageRequest, request: Request):
    manager = _manager(request)
    managed = _require(manager, cid)
    if managed.conversation.status == Status.WAITING_FOR_CONFIRMATION:
        raise HTTPException(
            status_code=409,
            detail="conversation is waiting for confirmation; use /confirm",
        )
    managed.conversation.send_message(body.text)
    manager.run_in_background(managed, managed.conversation.run)
    return _info(managed)


@router.post("/conversations/{cid}/confirm", response_model=ConversationInfo)
async def confirm(cid: str, body: ConfirmRequest, request: Request):
    manager = _manager(request)
    managed = _require(manager, cid)
    if managed.conversation.status != Status.WAITING_FOR_CONFIRMATION:
        raise HTTPException(
            status_code=409, detail="conversation is not waiting for confirmation"
        )
    if body.approve:
        trigger = managed.conversation.approve
    else:
        trigger = partial(managed.conversation.reject, body.reason)
    manager.run_in_background(managed, trigger)
    return _info(managed)


@router.delete("/conversations/{cid}")
async def delete_conversation(cid: str, request: Request):
    if not await _manager(request).delete(cid):
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"deleted": cid}


@router.websocket("/conversations/{cid}/ws")
async def conversation_ws(websocket: WebSocket, cid: str):
    managed = websocket.app.state.manager.get(cid)
    if managed is None:
        await websocket.close(code=4404)
        return

    # Subscribe before snapshotting so no event slips through the gap; dedupe the
    # overlap by id when streaming the live tail.
    queue = managed.broker.subscribe()
    await websocket.accept()
    try:
        replayed: set[str] = set()
        for event in list(managed.conversation.events):
            replayed.add(event.id)
            await websocket.send_text(event.model_dump_json())
        while True:
            event = await queue.get()
            if event.id in replayed:
                continue
            await websocket.send_text(event.model_dump_json())
    except WebSocketDisconnect:
        pass
    finally:
        managed.broker.unsubscribe(queue)
