"""conversation sandbox provider and id

Revision ID: 426538c29cac
Revises: 672c0e36ac5d
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '426538c29cac'
down_revision: str | None = '672c0e36ac5d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'conversations',
        sa.Column('sandbox_provider', sa.Text(), server_default='local', nullable=False),
    )
    op.add_column('conversations', sa.Column('sandbox_id', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('conversations', 'sandbox_id')
    op.drop_column('conversations', 'sandbox_provider')
