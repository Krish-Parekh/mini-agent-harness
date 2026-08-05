from __future__ import annotations

import uuid

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models import GitHubConnectionRow


class GitHubConnectionRepository:

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def get(self, user_id: uuid.UUID) -> GitHubConnectionRow | None:
        async with self._sessionmaker() as sess:
            return await sess.get(GitHubConnectionRow, user_id)

    async def token_for(self, user_id: uuid.UUID) -> str | None:
        row = await self.get(user_id)
        return row.access_token if row else None

    async def upsert(
        self,
        *,
        user_id: uuid.UUID,
        github_user_id: int,
        login: str,
        avatar_url: str | None,
        access_token: str,
        scopes: str | None,
    ) -> GitHubConnectionRow:
        async with self._sessionmaker() as sess:
            await sess.execute(
                pg_insert(GitHubConnectionRow)
                .values(
                    user_id=user_id,
                    github_user_id=github_user_id,
                    login=login,
                    avatar_url=avatar_url,
                    access_token=access_token,
                    scopes=scopes,
                )
                .on_conflict_do_update(
                    index_elements=[GitHubConnectionRow.user_id],
                    set_=dict(
                        github_user_id=github_user_id,
                        login=login,
                        avatar_url=avatar_url,
                        access_token=access_token,
                        scopes=scopes,
                        updated_at=func.now(),
                    ),
                )
            )
            await sess.commit()
            row = await sess.get(GitHubConnectionRow, user_id)
            assert row is not None
            return row

    async def delete(self, user_id: uuid.UUID) -> bool:
        async with self._sessionmaker() as sess:
            result = await sess.execute(
                delete(GitHubConnectionRow).where(
                    GitHubConnectionRow.user_id == user_id
                )
            )
            await sess.commit()
            return result.rowcount > 0
