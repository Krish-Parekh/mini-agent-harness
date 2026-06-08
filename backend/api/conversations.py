from __future__ import annotations

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from backend.api.deps import GitHubDep, ServiceDep, get_service
from backend.runtime.manager import ManagedConversation
from backend.schemas import (
    ConfirmRequest,
    ConversationInfo,
    CreateConversationRequest,
    SendMessageRequest,
    StatusUpdate,
)
from backend.service import ConversationService
from miniagent.conversation import Status

router = APIRouter()


async def _require(service: ConversationService, cid: str) -> ManagedConversation:
    managed = await service.get_or_revive(cid)
    if managed is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return managed


@router.post("/conversations", response_model=ConversationInfo)
async def create_conversation(
    body: CreateConversationRequest, service: ServiceDep, github: GitHubDep
):
    managed = service.create(
        repo=body.repo,
        branch=body.branch,
        workspace_dir=body.workspace_dir,
        confirm_mode=body.confirm_mode,
        token=github.token,
        initial_message=body.initial_message,
    )
    return service.info(managed)


@router.get("/conversations", response_model=list[ConversationInfo])
async def list_conversations(service: ServiceDep):
    return await service.list_infos()


@router.get("/conversations/{cid}", response_model=ConversationInfo)
async def get_conversation(cid: str, service: ServiceDep):
    return service.info(await _require(service, cid))


@router.get("/conversations/{cid}/events")
async def get_events(cid: str, service: ServiceDep):
    managed = await _require(service, cid)
    return [event.model_dump() for event in managed.conversation.events]


@router.post("/conversations/{cid}/messages", response_model=ConversationInfo)
async def send_message(cid: str, body: SendMessageRequest, service: ServiceDep):
    managed = await _require(service, cid)
    if managed.conversation.status == Status.WAITING_FOR_CONFIRMATION:
        raise HTTPException(
            status_code=409,
            detail="conversation is waiting for confirmation; use /confirm",
        )
    await service.send_message(managed, body.text)
    return service.info(managed)


@router.post("/conversations/{cid}/confirm", response_model=ConversationInfo)
async def confirm(cid: str, body: ConfirmRequest, service: ServiceDep):
    managed = await _require(service, cid)
    if managed.conversation.status != Status.WAITING_FOR_CONFIRMATION:
        raise HTTPException(
            status_code=409, detail="conversation is not waiting for confirmation"
        )
    await service.confirm(managed, body.approve, body.reason)
    return service.info(managed)


@router.delete("/conversations/{cid}")
async def delete_conversation(cid: str, service: ServiceDep):
    if not await service.delete(cid):
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"deleted": cid}


@router.websocket("/conversations/{cid}/ws")
async def conversation_ws(websocket: WebSocket, cid: str):
    service = get_service(websocket)
    managed = await service.get_or_revive(cid)
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
