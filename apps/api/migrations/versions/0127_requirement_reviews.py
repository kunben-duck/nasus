"""Append-only requirement evaluation, clarification and confirmation evidence."""
from alembic import op
import sqlalchemy as sa

revision = "0127_requirement_reviews"
down_revision = "0126_requirement_revisions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("requirement_review_events",
        sa.Column("event_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in (
            "project_id", "version_id", "us_id", "revision_id", "invocation_id", "kind", "actor_id", "recorded_at", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("invocation_id", "kind"),
        sa.ForeignKeyConstraint(["project_id", "version_id", "us_id", "revision_id"],
            ["requirement_revisions.project_id", "requirement_revisions.version_id",
             "requirement_revisions.us_id", "requirement_revisions.revision_id"]),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]))
    for key in ("project_id", "version_id", "us_id", "revision_id", "invocation_id"):
        op.create_index("ix_requirement_review_events_" + key, "requirement_review_events", [key])
    op.execute("CREATE TRIGGER immutable_requirement_review_events BEFORE UPDATE OR DELETE ON requirement_review_events "
        "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM requirement_review_events")):
        raise RuntimeError("cannot discard requirement review history")
    op.drop_table("requirement_review_events")
