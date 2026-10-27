"""Append-only evidence-driven investigation revisions; preserve old plan grants."""
from alembic import op
import sqlalchemy as sa

revision = "0084_investigation_revisions"
down_revision = "0083_structure_cancellation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("image_investigation_revisions",
        sa.Column("revision_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("goal_id", sa.String(), sa.ForeignKey("agent_goals.id"), nullable=False),
        sa.Column("image_revision_id", sa.String(), sa.ForeignKey("image_revisions.image_revision_id"), nullable=False),
        sa.Column("parent_revision_id", sa.String(), sa.ForeignKey("image_investigation_revisions.revision_id")),
        sa.Column("invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id"), nullable=False, unique=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("revision_hash", sa.String(), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("review_payload", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(), sa.ForeignKey("user_identities.user_id"), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "plan_id"], ["image_build_plans.project_id", "image_build_plans.plan_id"]),
        sa.UniqueConstraint("project_id", "goal_id", "plan_id", "revision_number"),
        sa.CheckConstraint("revision_number BETWEEN 1 AND 80"))
    op.create_index("ix_image_investigation_revisions_project_id", "image_investigation_revisions", ["project_id"])
    op.execute("CREATE TRIGGER immutable_image_investigation_revisions BEFORE UPDATE OR DELETE ON image_investigation_revisions FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM image_investigation_revisions)")):
        raise RuntimeError("Cannot discard populated investigation history.")
    op.drop_index("ix_image_investigation_revisions_project_id", table_name="image_investigation_revisions")
    op.drop_table("image_investigation_revisions")
