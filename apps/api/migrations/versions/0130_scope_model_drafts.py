"""Retain native model scope suggestions without granting review authority."""
from alembic import op
import sqlalchemy as sa

revision = "0130_scope_model_drafts"
down_revision = "0129_test_design_case_edits"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_scope_draft_events",
        sa.Column("event_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in (
            "project_id", "context_id", "invocation_id", "kind", "actor_id", "recorded_at", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("invocation_id", "kind"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.CheckConstraint("kind IN ('reserved', 'replied', 'failed', 'draft')"))
    op.create_index("ix_quality_scope_draft_events_project_id", "quality_scope_draft_events", ["project_id"])
    op.execute("CREATE TRIGGER immutable_quality_scope_draft_events BEFORE UPDATE OR DELETE ON quality_scope_draft_events "
        "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM quality_scope_draft_events")):
        raise RuntimeError("cannot discard retained scope draft history")
    op.drop_table("quality_scope_draft_events")
