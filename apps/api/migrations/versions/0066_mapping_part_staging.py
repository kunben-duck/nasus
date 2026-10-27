"""Append-only private mapping parts, never final mapping authority."""
from alembic import op
import sqlalchemy as sa

revision = "0066_mapping_part_staging"
down_revision = "0065_generation_batch_recovery"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_test_design_mapping_part_revisions",
        sa.Column("part_revision_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in (
            "project_id", "generation_id", "plan_digest", "authority_actor", "invocation_id", "artifact_ref", "content_hash")],
        sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("revision_sequence", sa.Integer(), nullable=False),
        sa.Column("expected_previous_revision_id", sa.String(), nullable=True),
        sa.Column("expected_previous_part_revision_id", sa.String(), nullable=True), sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("project_id", "generation_id", "plan_digest", "sequence", "authority_actor", "revision_sequence"),
        sa.UniqueConstraint("project_id", "generation_id", "plan_digest", "sequence", "authority_actor", "part_revision_id", name="uq_mapping_part_complete_pin"),
        sa.UniqueConstraint("expected_previous_part_revision_id"), sa.UniqueConstraint("invocation_id"),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.ForeignKeyConstraint(["project_id", "generation_id"], ["quality_test_design_results.project_id", "quality_test_design_results.generation_id"]),
        sa.ForeignKeyConstraint(["project_id", "generation_id", "expected_previous_revision_id"],
            ["quality_test_design_mapping_revisions.project_id", "quality_test_design_mapping_revisions.generation_id", "quality_test_design_mapping_revisions.revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "generation_id", "plan_digest", "sequence", "authority_actor", "expected_previous_part_revision_id"],
            ["quality_test_design_mapping_part_revisions.project_id", "quality_test_design_mapping_part_revisions.generation_id",
             "quality_test_design_mapping_part_revisions.plan_digest", "quality_test_design_mapping_part_revisions.sequence",
             "quality_test_design_mapping_part_revisions.authority_actor", "quality_test_design_mapping_part_revisions.part_revision_id"], name="fk_mapping_part_predecessor"),
        sa.CheckConstraint("sequence >= 0 AND sequence < 65536"),
        sa.CheckConstraint("revision_sequence BETWEEN 1 AND 1000 AND ((revision_sequence = 1 AND expected_previous_part_revision_id IS NULL) OR (revision_sequence > 1 AND expected_previous_part_revision_id IS NOT NULL))"))
    op.create_index("uq_mapping_part_first", "quality_test_design_mapping_part_revisions",
        ["project_id", "generation_id", "plan_digest", "sequence", "authority_actor"], unique=True,
        postgresql_where=sa.text("expected_previous_part_revision_id IS NULL"))
    op.execute("CREATE TRIGGER immutable_quality_test_design_mapping_part_revisions BEFORE UPDATE OR DELETE ON quality_test_design_mapping_part_revisions FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM quality_test_design_mapping_part_revisions")):
        raise RuntimeError("cannot downgrade while staged mapping parts exist")
    op.drop_table("quality_test_design_mapping_part_revisions")
