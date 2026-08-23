"""add versioned prompt registry

Revision ID: 0027_prompt_registry
Revises: 0026_llm_call_audit
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision = "0027_prompt_registry"
down_revision: Union[str, None] = "0026_llm_call_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prompt_definitions",
        sa.Column("prompt_id", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("input_schema_ref", sa.String(), nullable=False),
        sa.Column("output_schema_ref", sa.String(), nullable=False),
        sa.Column("safety_rules_ref", sa.String(), nullable=False),
        sa.Column("rollback_to", sa.String(), nullable=True),
        sa.Column("system_template", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("prompt_id", "version"),
    )
    op.create_index(
        "ix_prompt_definitions_content_hash",
        "prompt_definitions",
        ["content_hash"],
    )
    op.create_table(
        "prompt_selections",
        sa.Column("prompt_id", sa.String(), nullable=False),
        sa.Column("active_version", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("prompt_id"),
    )


def downgrade() -> None:
    op.drop_table("prompt_selections")
    op.drop_table("prompt_definitions")
