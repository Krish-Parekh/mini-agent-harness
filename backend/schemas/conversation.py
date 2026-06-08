from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from miniagent.confirm import ConfirmMode


class CreateConversationRequest(BaseModel):
    repo: str | None = None
    branch: str | None = None
    workspace_dir: str | None = None
    initial_message: str | None = None
    confirm_mode: ConfirmMode = "risky"


class SendMessageRequest(BaseModel):
    text: str
    model: str | None = None


class ConfirmRequest(BaseModel):
    approve: bool
    reason: str = "Action rejected by the user."


class StatusUpdate(BaseModel):
    """Pushed over the conversation WebSocket so clients track status without
    polling. Shares the `id`/`kind` shape of agent events so the same socket
    can carry both; `kind="status"` lets the client route it apart."""

    id: str = Field(default_factory=lambda: f"status-{uuid.uuid4().hex[:8]}")
    kind: str = "status"
    status: str


class ChangedFile(BaseModel):
    path: str
    additions: int
    deletions: int
    status: Literal["added", "modified", "deleted"]


class FileDiff(BaseModel):
    path: str
    patch: str


class FileContent(BaseModel):
    path: str
    content: str


class ConversationInfo(BaseModel):
    id: str
    status: str
    workspace_dir: str
    num_events: int
    repo: str | None = None
    branch: str | None = None
    title: str | None = None
    updated_at: datetime | None = None
