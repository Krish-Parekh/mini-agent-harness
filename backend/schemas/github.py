from __future__ import annotations

from pydantic import BaseModel


class RepoOut(BaseModel):
    full_name: str
    name: str
    owner: str
    private: bool
    default_branch: str
    description: str | None = None
    language: str | None = None
    updated_at: str


class ImportRepoRequest(BaseModel):
    repo: str  # a GitHub URL or "owner/name"
