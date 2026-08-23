"""add avatar preset to user identities

Revision ID: 0010_user_avatar_preset
Revises: 0009_user_avatar_url
Create Date: 2026-06-21 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_user_avatar_preset"
down_revision = "0009_user_avatar_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_identities", sa.Column("avatar_preset", sa.String(), nullable=True))
    op.create_index("ix_user_identities_avatar_preset", "user_identities", ["avatar_preset"])


def downgrade() -> None:
    op.drop_index("ix_user_identities_avatar_preset", table_name="user_identities")
    op.drop_column("user_identities", "avatar_preset")
