"""make tool invocation runtime state durable and idempotent

Revision ID: 0025_tool_runtime_state
Revises: 0024_api_rate_limits
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision = "0025_tool_runtime_state"
down_revision: Union[str, None] = "0024_api_rate_limits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tool_invocations",
        sa.Column("idempotency_scope", sa.String(), nullable=True),
    )
    op.add_column(
        "tool_invocations",
        sa.Column("idempotency_key", sa.String(), nullable=True),
    )
    op.add_column(
        "tool_invocations",
        sa.Column("idempotency_fingerprint", sa.String(), nullable=True),
    )
    op.add_column(
        "tool_invocations",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_tool_invocations_idempotency_scope",
        "tool_invocations",
        ["idempotency_scope"],
    )
    op.create_index(
        "ix_tool_invocations_idempotency_key",
        "tool_invocations",
        ["idempotency_key"],
    )
    op.create_unique_constraint(
        "uq_tool_invocation_idempotency",
        "tool_invocations",
        ["idempotency_scope", "tool_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_tool_invocation_idempotency",
        "tool_invocations",
        type_="unique",
    )
    op.drop_index(
        "ix_tool_invocations_idempotency_key",
        table_name="tool_invocations",
    )
    op.drop_index(
        "ix_tool_invocations_idempotency_scope",
        table_name="tool_invocations",
    )
    op.drop_column("tool_invocations", "revision")
    op.drop_column("tool_invocations", "idempotency_fingerprint")
    op.drop_column("tool_invocations", "idempotency_key")
    op.drop_column("tool_invocations", "idempotency_scope")
