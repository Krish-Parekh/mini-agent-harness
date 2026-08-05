from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models import ConversationRow, EventRow


class ConversationRepository:

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def record_event(
        self,
        *,
        cid: str,
        user_id: uuid.UUID,
        repo: str | None,
        branch: str | None,
        status: str,
        title: str | None,
        workspace_dir: str | None,
        plan: dict[str, Any] | None,
        implementing_plan: bool,
        event_id: str,
        seq: int,
        source: str,
        kind: str,
        payload: dict[str, Any],
    ) -> None:
        async with self._sessionmaker() as sess:
            await self._upsert(
                sess,
                cid=cid,
                user_id=user_id,
                repo=repo,
                branch=branch,
                status=status,
                title=title,
                workspace_dir=workspace_dir,
                plan=plan,
                implementing_plan=implementing_plan,
            )
            await sess.execute(
                pg_insert(EventRow)
                .values(
                    id=event_id,
                    conversation_id=cid,
                    seq=seq,
                    source=source,
                    kind=kind,
                    payload=payload,
                )
                .on_conflict_do_nothing(index_elements=[EventRow.id])
            )
            await sess.commit()

    async def upsert_conversation(
        self,
        *,
        cid: str,
        user_id: uuid.UUID,
        repo: str | None,
        branch: str | None,
        status: str,
        title: str | None,
        workspace_dir: str | None,
        plan: dict[str, Any] | None,
        implementing_plan: bool,
    ) -> None:
        async with self._sessionmaker() as sess:
            await self._upsert(
                sess,
                cid=cid,
                user_id=user_id,
                repo=repo,
                branch=branch,
                status=status,
                title=title,
                workspace_dir=workspace_dir,
                plan=plan,
                implementing_plan=implementing_plan,
            )
            await sess.commit()

    @staticmethod
    async def _upsert(
        sess: AsyncSession,
        *,
        cid: str,
        user_id: uuid.UUID,
        repo: str | None,
        branch: str | None,
        status: str,
        title: str | None,
        workspace_dir: str | None,
        plan: dict[str, Any] | None,
        implementing_plan: bool,
    ) -> None:
        values: dict[str, Any] = dict(
            id=cid,
            user_id=user_id,
            repo=repo,
            branch=branch,
            status=status,
            title=title,
            workspace_dir=workspace_dir,
            plan=plan,
            implementing_plan=implementing_plan,
        )
        set_: dict[str, Any] = dict(
            status=status,
            title=title,
            plan=plan,
            implementing_plan=implementing_plan,
            updated_at=func.now(),
        )
        await sess.execute(
            pg_insert(ConversationRow)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[ConversationRow.id],
                set_=set_,
            )
        )

    async def get(self, cid: str, user_id: uuid.UUID) -> ConversationRow | None:
        async with self._sessionmaker() as sess:
            row = await sess.get(ConversationRow, cid)
            return row if row is not None and row.user_id == user_id else None

    async def set_pr(self, cid: str, pr_number: int, pr_url: str) -> None:
        async with self._sessionmaker() as sess:
            await sess.execute(
                update(ConversationRow)
                .where(ConversationRow.id == cid)
                .values(pr_number=pr_number, pr_url=pr_url, updated_at=func.now())
            )
            await sess.commit()

    async def delete_events(self, cid: str, event_ids: list[str]) -> None:
        if not event_ids:
            return
        async with self._sessionmaker() as sess:
            await sess.execute(
                delete(EventRow).where(
                    EventRow.conversation_id == cid,
                    EventRow.id.in_(event_ids),
                )
            )
            await sess.commit()

    async def list_events(self, cid: str) -> list[EventRow]:
        async with self._sessionmaker() as sess:
            result = await sess.execute(
                select(EventRow)
                .where(EventRow.conversation_id == cid)
                .order_by(EventRow.seq)
            )
            return list(result.scalars().all())

    async def list_summaries(
        self, user_id: uuid.UUID
    ) -> list[tuple[ConversationRow, int]]:
        async with self._sessionmaker() as sess:
            stmt = (
                select(ConversationRow, func.count(EventRow.id))
                .outerjoin(EventRow, EventRow.conversation_id == ConversationRow.id)
                .where(ConversationRow.user_id == user_id)
                .group_by(ConversationRow.id)
                .order_by(ConversationRow.updated_at.desc())
            )
            result = await sess.execute(stmt)
            return [(row, count) for row, count in result.all()]

    async def delete(self, cid: str, user_id: uuid.UUID) -> bool:
        async with self._sessionmaker() as sess:
            row = await sess.get(ConversationRow, cid)
            if row is None or row.user_id != user_id:
                return False
            await sess.delete(row)
            await sess.commit()
            return True
