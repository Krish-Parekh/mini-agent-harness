"""conversation permission and plan modes

Revision ID: c37ad96e4ebd
Revises: 0552dc2769a8
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'c37ad96e4ebd'
down_revision: str | None = '0552dc2769a8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'conversations',
        sa.Column('plan_mode', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )
    op.add_column(
        'conversations',
        sa.Column('permission_mode', sa.Text(), server_default='auto', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('conversations', 'permission_mode')
    op.drop_column('conversations', 'plan_mode')
