"""memories

Revision ID: 0552dc2769a8
Revises: 5f6afc6bfcfd
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0552dc2769a8'
down_revision: str | None = '5f6afc6bfcfd'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('memories',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('repo', sa.Text(), nullable=True),
    sa.Column('path', sa.Text(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('conversation_id', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'repo', 'path', postgresql_nulls_not_distinct=True)
    )
    op.create_index(op.f('ix_memories_user_id'), 'memories', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_memories_user_id'), table_name='memories')
    op.drop_table('memories')
