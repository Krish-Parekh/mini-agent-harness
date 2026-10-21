from __future__ import annotations

import uuid

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models import MemoryRow


class MemoryRepository:

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def list_for_user(self, user_id: uuid.UUID) -> list[MemoryRow]:
        async with self._sessionmaker() as sess:
            result = await sess.execute(
                select(MemoryRow)
                .where(MemoryRow.user_id == user_id)
                .order_by(MemoryRow.repo.nulls_first(), MemoryRow.path)
            )
            return list(result.scalars().all())

    async def visible(self, user_id: uuid.UUID, repo: str | None) -> list[MemoryRow]:
        async with self._sessionmaker() as sess:
            result = await sess.execute(
                select(MemoryRow)
                .where(
                    MemoryRow.user_id == user_id,
                    or_(MemoryRow.repo.is_(None), MemoryRow.repo == repo),
                )
                .order_by(MemoryRow.repo.nulls_first(), MemoryRow.path)
            )
            return list(result.scalars().all())

    async def save(
        self,
        *,
        user_id: uuid.UUID,
        repo: str | None,
        path: str,
        content: str,
        conversation_id: str | None,
    ) -> None:
        async with self._sessionmaker() as sess:
            await sess.execute(
                pg_insert(MemoryRow)
                .values(
                    id=uuid.uuid4().hex[:12],
                    user_id=user_id,
                    repo=repo,
                    path=path,
                    content=content,
                    conversation_id=conversation_id,
                )
                .on_conflict_do_update(
                    index_elements=[MemoryRow.user_id, MemoryRow.repo, MemoryRow.path],
                    set_=dict(
                        content=content,
                        conversation_id=conversation_id,
                        updated_at=func.now(),
                    ),
                )
            )
            await sess.commit()

    async def delete(self, user_id: uuid.UUID, repo: str | None, path: str) -> None:
        async with self._sessionmaker() as sess:
            await sess.execute(
                delete(MemoryRow).where(
                    MemoryRow.user_id == user_id,
                    MemoryRow.repo.is_(None) if repo is None else MemoryRow.repo == repo,
                    MemoryRow.path == path,
                )
            )
            await sess.commit()

    async def update_content(
        self, user_id: uuid.UUID, memory_id: str, content: str
    ) -> MemoryRow | None:
        async with self._sessionmaker() as sess:
            row = await sess.scalar(
                update(MemoryRow)
                .where(MemoryRow.user_id == user_id, MemoryRow.id == memory_id)
                .values(content=content, updated_at=func.now())
                .returning(MemoryRow)
            )
            await sess.commit()
            return row

    async def delete_by_id(self, user_id: uuid.UUID, memory_id: str) -> bool:
        async with self._sessionmaker() as sess:
            result = await sess.execute(
                delete(MemoryRow).where(
                    MemoryRow.user_id == user_id, MemoryRow.id == memory_id
                )
            )
            await sess.commit()
            return result.rowcount > 0
