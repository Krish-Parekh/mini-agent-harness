from __future__ import annotations

from fastapi import APIRouter, HTTPException, WebSocket

from backend.api.deps import GitHubDep, ManagedDep, ServiceDep, get_service
from backend.api.streaming import stream_conversation
from backend.schemas import (
    ChangedFile,
    ConfirmRequest,
    ConversationInfo,
    CreateConversationRequest,
    FileContent,
    FileDiff,
    LaneUpdate,
    SendMessageRequest,
)
from miniagent.conversation import Status

router = APIRouter()


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
async def get_conversation(managed: ManagedDep, service: ServiceDep):
    return service.info(managed)


@router.get("/conversations/{cid}/events")
async def get_events(managed: ManagedDep):
    return [event.model_dump() for event in managed.conversation.events]


@router.get("/conversations/{cid}/changes", response_model=list[ChangedFile])
async def get_changes(managed: ManagedDep, service: ServiceDep):
    return service.list_changes(managed)


@router.get("/conversations/{cid}/changes/diff", response_model=FileDiff)
async def get_file_diff(managed: ManagedDep, path: str, service: ServiceDep):
    return service.file_diff(managed, path)


@router.get("/conversations/{cid}/files", response_model=list[str])
async def get_files(managed: ManagedDep, service: ServiceDep):
    return service.list_files(managed)


@router.get("/conversations/{cid}/files/content", response_model=FileContent)
async def get_file_content(managed: ManagedDep, path: str, service: ServiceDep):
    return service.file_content(managed, path)


@router.post("/conversations/{cid}/messages", response_model=ConversationInfo)
async def send_message(
    managed: ManagedDep, body: SendMessageRequest, service: ServiceDep
):
    if managed.conversation.status == Status.WAITING_FOR_CONFIRMATION:
        raise HTTPException(
            status_code=409,
            detail="conversation is waiting for confirmation; use /confirm",
        )
    await service.send_message(managed, body.text, body.model, body.plan_mode)
    return service.info(managed)


@router.post("/conversations/{cid}/plan/approve", response_model=ConversationInfo)
async def approve_plan(managed: ManagedDep, service: ServiceDep):
    if managed.conversation.plan is None:
        raise HTTPException(status_code=409, detail="no plan to approve")
    if managed.conversation.status in (
        Status.RUNNING,
        Status.WAITING_FOR_CONFIRMATION,
    ):
        raise HTTPException(status_code=409, detail="conversation is busy")
    await service.approve_plan(managed)
    return service.info(managed)


@router.post("/conversations/{cid}/confirm", response_model=ConversationInfo)
async def confirm(managed: ManagedDep, body: ConfirmRequest, service: ServiceDep):
    if managed.conversation.status != Status.WAITING_FOR_CONFIRMATION:
        raise HTTPException(
            status_code=409, detail="conversation is not waiting for confirmation"
        )
    await service.confirm(managed, body.approve, body.reason)
    return service.info(managed)


@router.post("/conversations/{cid}/stop", response_model=ConversationInfo)
async def stop_conversation(managed: ManagedDep, service: ServiceDep):
    await service.stop(managed)
    return service.info(managed)


@router.post("/conversations/{cid}/pr", response_model=ConversationInfo)
async def create_pr(managed: ManagedDep, service: ServiceDep, github: GitHubDep):
    if managed.repo is None:
        raise HTTPException(status_code=409, detail="conversation has no repository")
    if github.token is None:
        raise HTTPException(status_code=401, detail="GitHub is not connected")
    return await service.create_pr(managed, github.token)


@router.patch("/conversations/{cid}/lane", response_model=ConversationInfo)
async def update_lane(managed: ManagedDep, body: LaneUpdate, service: ServiceDep):
    await service.set_lane(managed, body.lane)
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
    await stream_conversation(websocket, managed)
