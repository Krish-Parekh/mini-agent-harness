from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models import (
    ConversationMcpRow,
    ConversationSkillRow,
    McpConnectionRow,
    RepoSkillRow,
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

    async def upsert_registry(
        self,
        *,
        user_id: uuid.UUID,
        registry_id: str,
        name: str,
        description: str,
        body: str,
        source_url: str,
    ) -> SkillRow:
        fields = dict(
            name=name, description=description, body=body, source_url=source_url
        )
        async with self._sessionmaker() as sess:
            skill_id = await sess.scalar(
                pg_insert(SkillRow)
                .values(id=_new_id(), user_id=user_id, registry_id=registry_id, **fields)
                .on_conflict_do_update(
                    index_elements=[SkillRow.user_id, SkillRow.registry_id],
                    set_=dict(**fields, updated_at=func.now()),
                )
                .returning(SkillRow.id)
            )
            await sess.commit()
            row = await sess.get(SkillRow, skill_id)
            assert row is not None
            return row

    async def repos_by_skill(self, user_id: uuid.UUID) -> dict[str, list[str]]:
        async with self._sessionmaker() as sess:
            result = await sess.execute(
                select(RepoSkillRow.skill_id, RepoSkillRow.repo)
                .where(RepoSkillRow.user_id == user_id)
                .order_by(RepoSkillRow.repo)
            )
            repos: dict[str, list[str]] = {}
            for skill_id, repo in result.all():
                repos.setdefault(skill_id, []).append(repo)
            return repos

    async def set_repo_enabled(
        self, user_id: uuid.UUID, repo: str, skill_id: str, enabled: bool
    ) -> None:
        async with self._sessionmaker() as sess:
            if enabled:
                await sess.execute(
                    pg_insert(RepoSkillRow)
                    .values(user_id=user_id, repo=repo, skill_id=skill_id)
                    .on_conflict_do_nothing()
                )
            else:
                await sess.execute(
                    delete(RepoSkillRow).where(
                        RepoSkillRow.user_id == user_id,
                        RepoSkillRow.repo == repo,
                        RepoSkillRow.skill_id == skill_id,
                    )
                )
            await sess.commit()

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

    async def enabled_for_conversation(
        self, cid: str, user_id: uuid.UUID | None = None, repo: str | None = None
    ) -> list[SkillRow]:
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
            rows = list(result.scalars().all())
            if user_id is not None and repo:
                result = await sess.execute(
                    select(SkillRow)
                    .join(RepoSkillRow, RepoSkillRow.skill_id == SkillRow.id)
                    .where(RepoSkillRow.user_id == user_id, RepoSkillRow.repo == repo)
                    .order_by(RepoSkillRow.created_at, SkillRow.name)
                )
                rows += result.scalars().all()
        return list({row.id: row for row in rows}.values())

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
