from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, Callable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Header, HTTPException
from fastapi.sse import EventSourceResponse, ServerSentEvent

from backend.api.deps import (
    SettingsDep,
    SkillsDep,
    CallerGitHubToken,
    CallerToken,
    CurrentUser,
    ManagedDep,
    RequiredGitHub,
    ServiceDep,
)
from backend.api.streaming import stream_conversation
from backend.runtime.attachments import AttachmentError
from backend.runtime.checkpoints import CheckpointError
from backend.schemas import (
    AttachmentIn,
    ChangedFile,
    ConfirmRequest,
    ConversationContext,
    ConversationInfo,
    CreateConversationRequest,
    FileContent,
    FileDiff,
    RewindRequest,
    RewindResult,
    SendMessageRequest,
    TurnInfo,
)
from miniagent.conversation import Status
from miniagent.sandbox.factory import default_provider, provider_problem
from miniagent.sandbox.base import SandboxError, SandboxExpired

router = APIRouter()

T = TypeVar("T")


async def _in_sandbox(fn: Callable[..., T], *args) -> T:
    """Sandbox reads can hit the network or boot a VM; keep them off the loop."""
    try:
        return await asyncio.to_thread(fn, *args)
    except SandboxExpired as exc:
        raise HTTPException(status_code=409, detail="sandbox_expired") from exc
    except SandboxError as exc:
        raise HTTPException(status_code=503, detail="sandbox_unavailable") from exc
    except CheckpointError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/conversations", response_model=ConversationInfo)
async def create_conversation(
    body: CreateConversationRequest,
    service: ServiceDep,
    user: CurrentUser,
    token: CallerGitHubToken,
    settings: SettingsDep,
    skills: SkillsDep,
    caller_token: CallerToken,
):
    try:
        attachments = await service.stage_attachments(
            user.id, caller_token, body.attachments
        )
    except AttachmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if body.sandbox_provider:
        problem = await asyncio.to_thread(provider_problem, settings, body.sandbox_provider)
        if problem:
            raise HTTPException(status_code=400, detail=problem)
    provider = body.sandbox_provider or await asyncio.to_thread(default_provider, settings)
    for skill_id in body.skill_ids:
        if await skills.get(skill_id, user.id) is None:
            raise HTTPException(status_code=404, detail="skill not found")
    managed = service.create(
        user_id=user.id,
        repo=body.repo,
        branch=body.branch,
        workspace_dir=body.workspace_dir,
        confirm_mode=body.confirm_mode,
        token=token,
        initial_message=body.initial_message,
        model=body.model,
        sandbox_provider=provider,
        skill_ids=body.skill_ids,
        attachments=attachments,
        storage_token=caller_token,
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
    return await _in_sandbox(service.context, managed)


@router.get("/conversations/{cid}/changes", response_model=list[ChangedFile])
async def get_changes(managed: ManagedDep, service: ServiceDep, scope: str = "all"):
    return await _in_sandbox(service.list_changes, managed, scope)


@router.get("/conversations/{cid}/changes/diff", response_model=FileDiff)
async def get_file_diff(
    managed: ManagedDep, path: str, service: ServiceDep, scope: str = "all"
):
    return await _in_sandbox(service.file_diff, managed, path, scope)


@router.get("/conversations/{cid}/turns", response_model=list[TurnInfo])
async def get_turns(managed: ManagedDep, service: ServiceDep):
    return await _in_sandbox(service.turns, managed)


@router.get("/conversations/{cid}/files", response_model=list[str])
async def get_files(managed: ManagedDep, service: ServiceDep):
    return await _in_sandbox(service.list_files, managed)


@router.get("/conversations/{cid}/files/content", response_model=FileContent)
async def get_file_content(managed: ManagedDep, path: str, service: ServiceDep):
    return await _in_sandbox(service.file_content, managed, path)


@router.post("/conversations/{cid}/messages", response_model=ConversationInfo)
async def send_message(
    managed: ManagedDep,
    body: SendMessageRequest,
    service: ServiceDep,
    caller_token: CallerToken,
):
    if managed.conversation.status == Status.WAITING_FOR_CONFIRMATION:
        raise HTTPException(
            status_code=409,
            detail="conversation is waiting for confirmation; use /confirm",
        )
    try:
        attachments = await service.stage_attachments(
            managed.user_id, caller_token, body.attachments
        )
    except AttachmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    try:
        await service.send_message(
            managed,
            body.text,
            body.model,
            body.plan_mode,
            body.client_event_id,
            attachments,
            caller_token,
        )
    except AttachmentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except SandboxError as exc:
        raise HTTPException(status_code=503, detail="sandbox_unavailable") from exc
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
    if not managed.conversation.awaits(body.tool_call_id):
        raise HTTPException(status_code=409, detail="this action is no longer pending")
    await service.confirm(managed, body.tool_call_id, body.approve, body.reason)
    return service.info(managed)


@router.post("/conversations/{cid}/rewind", response_model=RewindResult)
async def rewind(managed: ManagedDep, body: RewindRequest, service: ServiceDep):
    try:
        message = await service.rewind(managed, body.message_id)
    except CheckpointError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except SandboxError as exc:
        raise HTTPException(status_code=503, detail="sandbox_unavailable") from exc
    return RewindResult(
        text=message.text,
        attachments=[
            AttachmentIn(path=a.path, name=a.name, mime=a.mime, size=a.size, kind=a.kind)
            for a in message.attachments
        ],
    )


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
async def delete_conversation(
    cid: str, service: ServiceDep, user: CurrentUser, caller_token: CallerToken
):
    if not await service.delete(cid, user.id, caller_token):
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
