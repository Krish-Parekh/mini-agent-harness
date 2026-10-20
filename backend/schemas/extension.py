from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SkillOut(BaseModel):
    id: str
    name: str
    description: str
    source_url: str | None = None
    registry_id: str | None = None
    repos: list[str] = []
    created_at: datetime | None = None


class InstallSkillRequest(BaseModel):
    source: str
    skill_id: str
    repo: str


class SetSkillRepoRequest(BaseModel):
    repo: str
    enabled: bool


class McpConnectionOut(BaseModel):
    id: str
    name: str
    url: str
    auth_header: str | None = None
    created_at: datetime | None = None


class CreateMcpConnectionRequest(BaseModel):
    name: str
    url: str
    auth_header: str | None = None
    auth_value: str | None = None


class McpTestResult(BaseModel):
    ok: bool
    tools: list[str] = []
    error: str | None = None


class EnabledItem(BaseModel):
    id: str
    name: str
    enabled: bool
    skipped: bool = False


class SetEnabledRequest(BaseModel):
    enabled: bool
