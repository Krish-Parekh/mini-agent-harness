from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SkillInfo(BaseModel):
    name: str
    description: str
    scope: Literal["repo", "global"]
    repo: str | None = None


class SkillBody(BaseModel):
    name: str
    content: str
