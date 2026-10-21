from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from miniagent.tools.memory import MAX_MEMORY_CHARS


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    repo: str | None
    path: str
    content: str
    conversation_id: str | None
    created_at: datetime
    updated_at: datetime


class UpdateMemoryRequest(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_MEMORY_CHARS)
