"""add avatar url to user identities

Revision ID: 0009_user_avatar_url
Revises: 0008_user_identity_sessions
Create Date: 2026-06-21 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_user_avatar_url"
down_revision = "0008_user_identity_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_identities", sa.Column("avatar_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_identities", "avatar_url")
