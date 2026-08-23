"""add shared API rate limit windows

Revision ID: 0024_api_rate_limits
Revises: 0023_merged_resolutions
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision = "0024_api_rate_limits"
down_revision: Union[str, None] = "0023_merged_resolutions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_rate_limit_windows",
        sa.Column("scope_key", sa.String(), nullable=False),
        sa.Column("window_started_at_epoch", sa.BigInteger(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("expires_at_epoch", sa.BigInteger(), nullable=False),
        sa.Column("updated_at_epoch", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "scope_key",
            "window_started_at_epoch",
            name="pk_api_rate_limit_windows",
        ),
        sa.UniqueConstraint(
            "scope_key",
            "window_started_at_epoch",
            name="uq_api_rate_limit_window",
        ),
    )
    op.create_index(
        "ix_api_rate_limit_windows_scope",
        "api_rate_limit_windows",
        ["scope"],
    )
    op.create_index(
        "ix_api_rate_limit_windows_expires_at_epoch",
        "api_rate_limit_windows",
        ["expires_at_epoch"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_api_rate_limit_windows_expires_at_epoch",
        table_name="api_rate_limit_windows",
    )
    op.drop_index(
        "ix_api_rate_limit_windows_scope",
        table_name="api_rate_limit_windows",
    )
    op.drop_table("api_rate_limit_windows")
