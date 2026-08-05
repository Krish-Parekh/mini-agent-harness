"""events client_event_id

Revision ID: 672c0e36ac5d
Revises: fac3c9576006
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '672c0e36ac5d'
down_revision: str | None = 'fac3c9576006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('events', sa.Column('client_event_id', sa.Text(), nullable=True))
    op.create_index(
        'ix_events_conversation_client_event_id',
        'events',
        ['conversation_id', 'client_event_id'],
        unique=True,
        postgresql_where=sa.text('client_event_id IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index(
        'ix_events_conversation_client_event_id',
        table_name='events',
        postgresql_where=sa.text('client_event_id IS NOT NULL'),
    )
    op.drop_column('events', 'client_event_id')
