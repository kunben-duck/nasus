"""store uploaded avatars in object storage

Revision ID: 0011_user_avatar_object_storage
Revises: 0010_user_avatar_preset
Create Date: 2026-06-21 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_user_avatar_object_storage"
down_revision = "0010_user_avatar_preset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_identities", sa.Column("avatar_object_ref", sa.Text(), nullable=True))
    op.add_column("user_identities", sa.Column("avatar_mime_type", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_identities", "avatar_mime_type")
    op.drop_column("user_identities", "avatar_object_ref")
