"""Independent append-only business rule authority; never upgrades source projections."""
from alembic import op
import sqlalchemy as sa

revision = "0052_business_rule_authority"
down_revision = "0051_context_packs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_business_rule_revisions",
        sa.Column("revision_id", sa.String(), primary_key=True),
        *[sa.Column(k, sa.String(), nullable=False) for k in ("rule_id", "project_id", "image_revision_id", "object_id",
            "binding_id", "source_revision_id", "document_revision_id", "status", "invocation_id", "artifact_ref", "content_hash")],
        sa.Column("previous_revision_id", sa.String()), sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("rule_id", "sequence"), sa.UniqueConstraint("project_id", "rule_id", "revision_id"),
        sa.UniqueConstraint("previous_revision_id"), sa.UniqueConstraint("invocation_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        sa.ForeignKeyConstraint(["image_revision_id", "object_id", "document_revision_id"],
            ["image_object_members.image_revision_id", "image_object_members.object_id", "image_object_members.document_revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "binding_id", "source_revision_id", "document_revision_id"],
            ["source_document_revisions.project_id", "source_document_revisions.binding_id", "source_document_revisions.source_revision_id", "source_document_revisions.document_revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "rule_id", "previous_revision_id"],
            ["quality_business_rule_revisions.project_id", "quality_business_rule_revisions.rule_id", "quality_business_rule_revisions.revision_id"]),
        sa.CheckConstraint("status IN ('approved', 'withdrawn')"),
        sa.CheckConstraint("sequence BETWEEN 1 AND 1000 AND ((sequence = 1 AND previous_revision_id IS NULL AND status = 'approved') OR (sequence > 1 AND previous_revision_id IS NOT NULL))"))
    op.create_index("ix_quality_business_rule_revisions_rule_id", "quality_business_rule_revisions", ["rule_id"])
    op.create_index("uq_business_rule_first", "quality_business_rule_revisions", ["rule_id"], unique=True,
                    postgresql_where=sa.text("previous_revision_id IS NULL"))
    op.execute("CREATE TRIGGER immutable_quality_business_rule_revisions BEFORE UPDATE OR DELETE ON quality_business_rule_revisions FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM quality_business_rule_revisions")):
        raise RuntimeError("cannot downgrade while business rule authority revisions exist")
    op.drop_table("quality_business_rule_revisions")
