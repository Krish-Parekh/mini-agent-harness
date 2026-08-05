from __future__ import annotations

import uuid

from backend.models import GitHubConnectionRow, UserRow
from backend.schemas import ConversationInfo


class FakeUserRepository:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, UserRow] = {}

    async def upsert(
        self, *, user_id: uuid.UUID, email: str | None, avatar_url: str | None
    ) -> UserRow:
        row = self.rows.get(user_id) or UserRow(id=user_id)
        row.email = email
        row.avatar_url = avatar_url
        self.rows[user_id] = row
        return row

    async def get(self, user_id: uuid.UUID) -> UserRow | None:
        return self.rows.get(user_id)


class FakeConnectionRepository:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, GitHubConnectionRow] = {}

    async def get(self, user_id: uuid.UUID) -> GitHubConnectionRow | None:
        return self.rows.get(user_id)

    async def token_for(self, user_id: uuid.UUID) -> str | None:
        row = self.rows.get(user_id)
        return row.access_token if row else None

    async def upsert(self, **kwargs) -> GitHubConnectionRow:
        row = GitHubConnectionRow(**kwargs)
        self.rows[kwargs["user_id"]] = row
        return row

    async def delete(self, user_id: uuid.UUID) -> bool:
        return self.rows.pop(user_id, None) is not None


class FakeManaged:

    def __init__(self, cid: str, user_id: uuid.UUID) -> None:
        self.id = cid
        self.user_id = user_id
        self.repo = None


class FakeConversationService:

    def __init__(self) -> None:
        self.conversations: dict[str, FakeManaged] = {}

    def add(self, cid: str, user_id: uuid.UUID) -> FakeManaged:
        managed = FakeManaged(cid, user_id)
        self.conversations[cid] = managed
        return managed

    async def get_or_revive(self, cid: str, user_id: uuid.UUID):
        managed = self.conversations.get(cid)
        return managed if managed and managed.user_id == user_id else None

    async def list_infos(self, user_id: uuid.UUID) -> list[ConversationInfo]:
        return [
            ConversationInfo(
                id=m.id, status="idle", workspace_dir="/tmp", num_events=0
            )
            for m in self.conversations.values()
            if m.user_id == user_id
        ]

    async def delete(self, cid: str, user_id: uuid.UUID) -> bool:
        managed = self.conversations.get(cid)
        if managed is None or managed.user_id != user_id:
            return False
        del self.conversations[cid]
        return True
