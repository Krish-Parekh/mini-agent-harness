from __future__ import annotations

import uuid

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models import UserRow


class UserRepository:

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def upsert(
        self, *, user_id: uuid.UUID, email: str | None, avatar_url: str | None
    ) -> UserRow:
        async with self._sessionmaker() as sess:
            await sess.execute(
                pg_insert(UserRow)
                .values(id=user_id, email=email, avatar_url=avatar_url)
                .on_conflict_do_update(
                    index_elements=[UserRow.id],
                    set_=dict(
                        email=email, avatar_url=avatar_url, updated_at=func.now()
                    ),
                )
            )
            await sess.commit()
            row = await sess.get(UserRow, user_id)
            assert row is not None
            return row

    async def get(self, user_id: uuid.UUID) -> UserRow | None:
        async with self._sessionmaker() as sess:
            return await sess.get(UserRow, user_id)
