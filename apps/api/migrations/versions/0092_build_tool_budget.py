"""Append-only cumulative tool reservations for newly created build goals."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0092_build_tool_budget"
down_revision = "0091_build_gap_ownership"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_goals", sa.Column("tool_budget_hash", sa.String(), nullable=True))
    op.create_table("image_build_tool_budgets",
        sa.Column("goal_id", sa.String(), sa.ForeignKey("agent_goals.id"), primary_key=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False))
    op.create_table("image_build_tool_consumptions",
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), primary_key=True),
        sa.Column("goal_id", sa.String(), sa.ForeignKey("image_build_tool_budgets.goal_id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("work_key", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("goal_id", "sequence"), sa.UniqueConstraint("goal_id", "work_key"),
        sa.CheckConstraint("sequence BETWEEN 1 AND 1000"))
    op.create_index("ix_image_build_tool_consumptions_goal_id", "image_build_tool_consumptions", ["goal_id"])
    for table in ("image_build_tool_budgets", "image_build_tool_consumptions"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")
    op.execute("""CREATE FUNCTION nasus_preserve_build_tool_budget_pin() RETURNS trigger AS $$
        BEGIN
            IF OLD.tool_budget_hash IS NOT NULL AND NEW.tool_budget_hash IS DISTINCT FROM OLD.tool_budget_hash THEN
                RAISE EXCEPTION 'build tool budget pin is immutable';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql""")
    op.execute("CREATE TRIGGER preserve_build_tool_budget_pin BEFORE UPDATE ON agent_goals FOR EACH ROW EXECUTE FUNCTION nasus_preserve_build_tool_budget_pin()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM image_build_tool_budgets) OR EXISTS (SELECT 1 FROM agent_goals WHERE tool_budget_hash IS NOT NULL)")):
        raise RuntimeError("Cannot discard populated cumulative build tool budgets.")
    op.execute("DROP TRIGGER preserve_build_tool_budget_pin ON agent_goals")
    op.execute("DROP FUNCTION nasus_preserve_build_tool_budget_pin()")
    op.drop_table("image_build_tool_consumptions")
    op.drop_table("image_build_tool_budgets")
    op.drop_column("agent_goals", "tool_budget_hash")
