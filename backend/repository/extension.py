from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models import (
    ConversationMcpRow,
    ConversationSkillRow,
    McpConnectionRow,
    SkillRow,
)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class SkillRepository:

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def list_for_user(self, user_id: uuid.UUID) -> list[SkillRow]:
        async with self._sessionmaker() as sess:
            result = await sess.execute(
                select(SkillRow)
                .where(SkillRow.user_id == user_id)
                .order_by(SkillRow.created_at.desc())
            )
            return list(result.scalars().all())

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        description: str,
        body: str,
        source_url: str | None = None,
    ) -> SkillRow:
        row = SkillRow(
            id=_new_id(),
            user_id=user_id,
            name=name,
            description=description,
            body=body,
            source_url=source_url,
        )
        async with self._sessionmaker() as sess:
            sess.add(row)
            await sess.commit()
            await sess.refresh(row)
            return row

    async def get(self, skill_id: str, user_id: uuid.UUID) -> SkillRow | None:
        async with self._sessionmaker() as sess:
            row = await sess.get(SkillRow, skill_id)
            return row if row is not None and row.user_id == user_id else None

    async def delete(self, skill_id: str, user_id: uuid.UUID) -> bool:
        async with self._sessionmaker() as sess:
            row = await sess.get(SkillRow, skill_id)
            if row is None or row.user_id != user_id:
                return False
            await sess.delete(row)
            await sess.commit()
            return True

    async def enabled_for_conversation(self, cid: str) -> list[SkillRow]:
        async with self._sessionmaker() as sess:
            result = await sess.execute(
                select(SkillRow)
                .join(
                    ConversationSkillRow,
                    ConversationSkillRow.skill_id == SkillRow.id,
                )
                .where(ConversationSkillRow.conversation_id == cid)
                .order_by(ConversationSkillRow.created_at)
            )
            return list(result.scalars().all())

    async def set_enabled(self, cid: str, skill_id: str, enabled: bool) -> None:
        async with self._sessionmaker() as sess:
            if enabled:
                exists = await sess.get(ConversationSkillRow, (cid, skill_id))
                if exists is None:
                    sess.add(
                        ConversationSkillRow(conversation_id=cid, skill_id=skill_id)
                    )
            else:
                await sess.execute(
                    delete(ConversationSkillRow).where(
                        ConversationSkillRow.conversation_id == cid,
                        ConversationSkillRow.skill_id == skill_id,
                    )
                )
            await sess.commit()


class McpConnectionRepository:

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def list_for_user(self, user_id: uuid.UUID) -> list[McpConnectionRow]:
        async with self._sessionmaker() as sess:
            result = await sess.execute(
                select(McpConnectionRow)
                .where(McpConnectionRow.user_id == user_id)
                .order_by(McpConnectionRow.created_at.desc())
            )
            return list(result.scalars().all())

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        url: str,
        auth_header: str | None,
        auth_value: str | None,
    ) -> McpConnectionRow:
        row = McpConnectionRow(
            id=_new_id(),
            user_id=user_id,
            name=name,
            url=url,
            auth_header=auth_header,
            auth_value=auth_value,
        )
        async with self._sessionmaker() as sess:
            sess.add(row)
            await sess.commit()
            await sess.refresh(row)
            return row

    async def get(
        self, connection_id: str, user_id: uuid.UUID
    ) -> McpConnectionRow | None:
        async with self._sessionmaker() as sess:
            row = await sess.get(McpConnectionRow, connection_id)
            return row if row is not None and row.user_id == user_id else None

    async def delete(self, connection_id: str, user_id: uuid.UUID) -> bool:
        async with self._sessionmaker() as sess:
            row = await sess.get(McpConnectionRow, connection_id)
            if row is None or row.user_id != user_id:
                return False
            await sess.delete(row)
            await sess.commit()
            return True

    async def enabled_for_conversation(self, cid: str) -> list[McpConnectionRow]:
        async with self._sessionmaker() as sess:
            result = await sess.execute(
                select(McpConnectionRow)
                .join(
                    ConversationMcpRow,
                    ConversationMcpRow.mcp_connection_id == McpConnectionRow.id,
                )
                .where(ConversationMcpRow.conversation_id == cid)
                .order_by(ConversationMcpRow.created_at)
            )
            return list(result.scalars().all())

    async def set_enabled(self, cid: str, connection_id: str, enabled: bool) -> None:
        async with self._sessionmaker() as sess:
            if enabled:
                exists = await sess.get(ConversationMcpRow, (cid, connection_id))
                if exists is None:
                    sess.add(
                        ConversationMcpRow(
                            conversation_id=cid, mcp_connection_id=connection_id
                        )
                    )
            else:
                await sess.execute(
                    delete(ConversationMcpRow).where(
                        ConversationMcpRow.conversation_id == cid,
                        ConversationMcpRow.mcp_connection_id == connection_id,
                    )
                )
            await sess.commit()
