from __future__ import annotations

from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from fastapi.sse import EventSourceResponse, ServerSentEvent

from backend.api.deps import (
    CallerGitHubToken,
    CurrentUser,
    ManagedDep,
    RequiredGitHub,
    ServiceDep,
)
from backend.api.streaming import stream_conversation
from backend.schemas import (
    ChangedFile,
    ConfirmRequest,
    ConversationContext,
    ConversationInfo,
    CreateConversationRequest,
    FileContent,
    FileDiff,
    SendMessageRequest,
)
from miniagent.conversation import Status

router = APIRouter()


@router.post("/conversations", response_model=ConversationInfo)
async def create_conversation(
    body: CreateConversationRequest,
    service: ServiceDep,
    user: CurrentUser,
    token: CallerGitHubToken,
):
    managed = service.create(
        user_id=user.id,
        repo=body.repo,
        branch=body.branch,
        workspace_dir=body.workspace_dir,
        confirm_mode=body.confirm_mode,
        token=token,
        initial_message=body.initial_message,
    )
    return service.info(managed)


@router.get("/conversations", response_model=list[ConversationInfo])
async def list_conversations(service: ServiceDep, user: CurrentUser):
    return await service.list_infos(user.id)


@router.get("/conversations/{cid}", response_model=ConversationInfo)
async def get_conversation(managed: ManagedDep, service: ServiceDep):
    return service.info(managed)


@router.get("/conversations/{cid}/events")
async def get_events(managed: ManagedDep):
    return [event.model_dump() for event in managed.conversation.events]


@router.get("/conversations/{cid}/context", response_model=ConversationContext)
async def get_context(managed: ManagedDep, service: ServiceDep):
    return service.context(managed)


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
    await service.send_message(
        managed, body.text, body.model, body.plan_mode, body.client_event_id
    )
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
async def create_pr(managed: ManagedDep, service: ServiceDep, gh: RequiredGitHub):
    if managed.repo is None:
        raise HTTPException(status_code=409, detail="conversation has no repository")
    return await service.create_pr(managed, gh.token)


@router.delete("/conversations/{cid}")
async def delete_conversation(cid: str, service: ServiceDep, user: CurrentUser):
    if not await service.delete(cid, user.id):
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"deleted": cid}


@router.get(
    "/conversations/{cid}/events/stream", response_class=EventSourceResponse
)
async def conversation_event_stream(
    managed: ManagedDep,
    last_event_id: Annotated[int | None, Header()] = None,
) -> AsyncIterable[ServerSentEvent]:
    async for frame in stream_conversation(managed, last_event_id):
        yield frame
