"""Register exact script/review ancestry without altering the v1 derivation graph."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

revision = "0100_automation_provenance"
down_revision = "0099_automation_script_reviews"
branch_labels = None
depends_on = None

TABLES = ("quality_automation_provenance", "quality_automation_provenance_edges")


def upgrade():
    node, edge = TABLES
    op.create_table(node,
        *(sa.Column(key, sa.String(), primary_key=True) for key in ("project_id", "node_key")),
        *(sa.Column(key, sa.String(), nullable=False) for key in ("context_id", "kind", "artifact_id",
            "artifact_hash", "invocation_id", "script_revision_id")),
        sa.Column("review_revision_id", sa.String(), nullable=True),
        sa.Column("policy_revision", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "context_id", "node_key", "content_hash", name="uq_automation_provenance_pin"),
        sa.ForeignKeyConstraint(["project_id", "context_id"],
            ["system_image_context_packs.project_id", "system_image_context_packs.context_id"]),
        sa.ForeignKeyConstraint(["project_id", "script_revision_id"],
            ["quality_automation_script_revisions.project_id", "quality_automation_script_revisions.script_revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "script_revision_id", "review_revision_id"],
            ["quality_automation_script_reviews.project_id", "quality_automation_script_reviews.script_revision_id",
             "quality_automation_script_reviews.revision_id"]),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.CheckConstraint("(kind = 'script' AND review_revision_id IS NULL AND artifact_id = script_revision_id) OR "
            "(kind = 'script_review' AND review_revision_id IS NOT NULL AND artifact_id = review_revision_id)"),
        sa.CheckConstraint("node_key = kind || ':' || artifact_id"),
        sa.CheckConstraint("policy_revision = 'nasus.automation-provenance.v1'"))
    op.create_index("ix_automation_provenance_context", node,
        ["project_id", "context_id", "kind", "artifact_id"])
    op.create_table(edge,
        *(sa.Column(key, sa.String(), primary_key=True) for key in ("project_id", "node_key", "parent_key")),
        *(sa.Column(key, sa.String(), nullable=False) for key in (
            "context_id", "node_hash", "parent_hash", "parent_artifact_hash")),
        *(sa.Column(key, sa.String(), nullable=True) for key in ("test_design_key", "automation_key")),
        sa.ForeignKeyConstraint(["project_id", "context_id", "node_key", "node_hash"],
            [node + "." + key for key in ("project_id", "context_id", "node_key", "content_hash")]),
        sa.ForeignKeyConstraint(["project_id", "context_id", "test_design_key", "parent_hash"],
            ["system_image_derivations." + key for key in ("project_id", "context_id", "node_key", "content_hash")]),
        sa.ForeignKeyConstraint(["project_id", "context_id", "automation_key", "parent_hash"],
            [node + "." + key for key in ("project_id", "context_id", "node_key", "content_hash")]),
        sa.CheckConstraint("(test_design_key = parent_key AND automation_key IS NULL) OR "
            "(automation_key = parent_key AND test_design_key IS NULL)"),
        sa.CheckConstraint("test_design_key IS NOT NULL OR automation_key IS NOT NULL"),
        sa.CheckConstraint("node_key <> parent_key"))
    op.create_index("ix_automation_provenance_parent", edge, ["project_id", "parent_key", "node_key"])
    from apps.api.app.infrastructure.persistence.automation_provenance_v1 import AutomationProvenanceProjectorV1
    with Session(bind=op.get_bind()) as session:
        AutomationProvenanceProjectorV1().backfill(session)
        session.commit()
    for table in TABLES:
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if any(op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")) for table in TABLES):
        raise RuntimeError("Cannot discard populated automation provenance history.")
    for table in reversed(TABLES):
        op.drop_table(table)
