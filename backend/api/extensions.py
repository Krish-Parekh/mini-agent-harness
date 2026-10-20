from __future__ import annotations

from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query

from backend.api.deps import (
    ConnectionsDep,
    CurrentUser,
    ManagedDep,
    McpDep,
    SkillsDep,
)
from backend.models import SkillRow
from backend.schemas.extension import (
    CreateMcpConnectionRequest,
    EnabledItem,
    InstallSkillRequest,
    McpConnectionOut,
    McpTestResult,
    SetEnabledRequest,
    SetSkillRepoRequest,
    SkillOut,
)
from backend.service.extension import ImportError_, McpService, SkillService
from miniagent.skills_registry import SkillHit

router = APIRouter()


LOCAL_HOSTS = {"localhost", "127.0.0.1"}


def _allowed_mcp_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return bool(parsed.hostname)
    return parsed.scheme == "http" and parsed.hostname in LOCAL_HOSTS




def _skill_out(row: SkillRow, repos: list[str]) -> SkillOut:
    return SkillOut(
        id=row.id,
        name=row.name,
        description=row.description,
        source_url=row.source_url,
        registry_id=row.registry_id,
        repos=repos,
        created_at=row.created_at,
    )


@router.get("/skills", response_model=list[SkillOut])
async def list_skills(user: CurrentUser, skills: SkillsDep):
    repos = await skills.repos_by_skill(user.id)
    return [
        _skill_out(row, repos.get(row.id, []))
        for row in await skills.list_for_user(user.id)
    ]


@router.get("/skills/search", response_model=list[SkillHit])
async def search_skills(
    user: CurrentUser,
    skills: SkillsDep,
    q: Annotated[str, Query(min_length=1, max_length=100)],
):
    try:
        return await SkillService(skills).search(q)
    except ImportError_ as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@router.post("/skills/install", response_model=SkillOut)
async def install_skill(
    body: InstallSkillRequest,
    user: CurrentUser,
    skills: SkillsDep,
    connections: ConnectionsDep,
):
    try:
        row = await SkillService(skills, connections).install(
            user.id, body.source, body.skill_id, body.repo
        )
    except ImportError_ as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    repos = await skills.repos_by_skill(user.id)
    return _skill_out(row, repos.get(row.id, []))


@router.put("/skills/{skill_id}/repos", response_model=SkillOut)
async def set_skill_repo(
    skill_id: str, body: SetSkillRepoRequest, user: CurrentUser, skills: SkillsDep
):
    row = await skills.get(skill_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="skill not found")
    await skills.set_repo_enabled(user.id, body.repo, skill_id, body.enabled)
    repos = await skills.repos_by_skill(user.id)
    return _skill_out(row, repos.get(row.id, []))


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str, user: CurrentUser, skills: SkillsDep):
    if not await skills.delete(skill_id, user.id):
        raise HTTPException(status_code=404, detail="skill not found")
    return {"deleted": skill_id}


@router.get("/conversations/{cid}/skills", response_model=list[EnabledItem])
async def list_conversation_skills(
    managed: ManagedDep, user: CurrentUser, skills: SkillsDep
):
    owned = await skills.list_for_user(user.id)
    included, skipped = await SkillService(skills).enabled_catalog(
        managed.conversation.id, managed.user_id, managed.repo
    )
    enabled = {row.id for row in included}
    over_budget = {row.id for row in skipped}
    return [
        EnabledItem(
            id=row.id,
            name=row.name,
            enabled=row.id in enabled or row.id in over_budget,
            skipped=row.id in over_budget,
        )
        for row in owned
    ]


@router.put("/conversations/{cid}/skills/{skill_id}", response_model=EnabledItem)
async def set_conversation_skill(
    skill_id: str,
    body: SetEnabledRequest,
    managed: ManagedDep,
    user: CurrentUser,
    skills: SkillsDep,
):
    skill = await skills.get(skill_id, user.id)
    if skill is None:
        raise HTTPException(status_code=404, detail="skill not found")
    await skills.set_enabled(managed.conversation.id, skill_id, body.enabled)
    return EnabledItem(id=skill.id, name=skill.name, enabled=body.enabled)


@router.get("/mcp/connections", response_model=list[McpConnectionOut])
async def list_connections(user: CurrentUser, mcp: McpDep):
    return await mcp.list_for_user(user.id)


@router.post("/mcp/connections", response_model=McpConnectionOut)
async def create_connection(
    body: CreateMcpConnectionRequest, user: CurrentUser, mcp: McpDep
):
    if not _allowed_mcp_url(body.url):
        raise HTTPException(
            status_code=400,
            detail="MCP server URLs must use https (or localhost for testing).",
        )
    return await mcp.create(
        user_id=user.id,
        name=body.name,
        url=body.url,
        auth_header=body.auth_header,
        auth_value=body.auth_value,
    )


@router.delete("/mcp/connections/{connection_id}")
async def delete_connection(connection_id: str, user: CurrentUser, mcp: McpDep):
    if not await mcp.delete(connection_id, user.id):
        raise HTTPException(status_code=404, detail="connection not found")
    return {"deleted": connection_id}


@router.post("/mcp/connections/{connection_id}/test", response_model=McpTestResult)
async def test_connection(connection_id: str, user: CurrentUser, mcp: McpDep):
    row = await mcp.get(connection_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="connection not found")
    ok, tools, error = await McpService(mcp).test(row)
    return McpTestResult(ok=ok, tools=tools, error=error)


@router.get("/conversations/{cid}/mcp", response_model=list[EnabledItem])
async def list_conversation_mcp(
    managed: ManagedDep, user: CurrentUser, mcp: McpDep
):
    owned = await mcp.list_for_user(user.id)
    enabled = {
        row.id for row in await mcp.enabled_for_conversation(managed.conversation.id)
    }
    return [
        EnabledItem(
            id=row.id,
            name=row.name,
            enabled=row.id in enabled,
            skipped=row.id in enabled and row.id in managed.mcp_skipped,
        )
        for row in owned
    ]


@router.put("/conversations/{cid}/mcp/{connection_id}", response_model=EnabledItem)
async def set_conversation_mcp(
    connection_id: str,
    body: SetEnabledRequest,
    managed: ManagedDep,
    user: CurrentUser,
    mcp: McpDep,
):
    row = await mcp.get(connection_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="connection not found")
    await mcp.set_enabled(managed.conversation.id, connection_id, body.enabled)
    return EnabledItem(id=row.id, name=row.name, enabled=body.enabled)
