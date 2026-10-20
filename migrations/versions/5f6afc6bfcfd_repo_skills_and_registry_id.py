"""repo skills and registry id

Revision ID: 5f6afc6bfcfd
Revises: e2a594cf6e97
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '5f6afc6bfcfd'
down_revision: str | None = 'e2a594cf6e97'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('repo_skills',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('repo', sa.Text(), nullable=False),
    sa.Column('skill_id', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'repo', 'skill_id')
    )
    op.add_column('skills', sa.Column('registry_id', sa.Text(), nullable=True))
    op.create_unique_constraint(
        'skills_user_id_registry_id_key', 'skills', ['user_id', 'registry_id']
    )


def downgrade() -> None:
    op.drop_constraint('skills_user_id_registry_id_key', 'skills', type_='unique')
    op.drop_column('skills', 'registry_id')
    op.drop_table('repo_skills')
