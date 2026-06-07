from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from miniagent.confirm import ConfirmMode


class CreateConversationRequest(BaseModel):
    repo: str | None = None
    branch: str | None = None
    workspace_dir: str | None = None
    initial_message: str | None = None
    confirm_mode: ConfirmMode = "risky"


class SendMessageRequest(BaseModel):
    text: str


class ConfirmRequest(BaseModel):
    approve: bool
    reason: str = "Action rejected by the user."


class ConversationInfo(BaseModel):
    id: str
    status: str
    workspace_dir: str
    num_events: int
    repo: str | None = None
    branch: str | None = None
    title: str | None = None
    updated_at: datetime | None = None
