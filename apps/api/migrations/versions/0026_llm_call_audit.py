"""add durable redacted LLM call audit facts

Revision ID: 0026_llm_call_audit
Revises: 0025_tool_runtime_state
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision = "0026_llm_call_audit"
down_revision: Union[str, None] = "0025_tool_runtime_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("route", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("selected_provider", sa.String(), nullable=False),
        sa.Column("selected_model_name", sa.String(), nullable=False),
        sa.Column("runtime_mode", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("prompt_id", sa.String(), nullable=True),
        sa.Column("prompt_version", sa.String(), nullable=True),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("version_id", sa.String(), nullable=True),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("agent_goal_id", sa.String(), nullable=True),
        sa.Column("tool_invocation_id", sa.String(), nullable=True),
        sa.Column("model_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_source", sa.String(), nullable=False, server_default="none"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("response_hash", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "occurred_at",
        "route",
        "purpose",
        "provider",
        "model_name",
        "runtime_mode",
        "outcome",
        "prompt_id",
        "project_id",
        "version_id",
        "task_id",
        "conversation_id",
        "agent_goal_id",
        "tool_invocation_id",
        "request_hash",
    ):
        op.create_index(f"ix_llm_calls_{column}", "llm_calls", [column])


def downgrade() -> None:
    op.drop_table("llm_calls")
