from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.db import Base


class MemoryRow(Base):

    __tablename__ = "memories"
    __table_args__ = (
        UniqueConstraint("user_id", "repo", "path", postgresql_nulls_not_distinct=True),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    repo: Mapped[str | None] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    conversation_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
