"""Pin reviewed assertions and decisions in immutable child image candidates."""
from alembic import op
import sqlalchemy as sa

revision = "0045_image_review_membership"
down_revision = "0044_link_decisions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("image_revisions", sa.Column("parent_revision_id", sa.String(), nullable=True))
    op.add_column("image_revisions", sa.Column("parent_artifact_hash", sa.String(), nullable=True))
    op.add_column("image_revisions", sa.Column("assertion_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_foreign_key("fk_image_review_parent", "image_revisions", "image_revisions",
        ["project_id", "parent_revision_id"], ["project_id", "image_revision_id"])
    op.create_check_constraint("ck_image_review_membership", "image_revisions",
        "(policy_version = 'nasus.image-candidate.v1' AND parent_revision_id IS NULL AND parent_artifact_hash IS NULL AND assertion_count = 0) OR (policy_version = 'nasus.image-candidate.v2' AND parent_revision_id IS NOT NULL AND parent_revision_id <> image_revision_id AND parent_artifact_hash IS NOT NULL AND assertion_count BETWEEN 1 AND 1000)")
    op.create_table("image_assertion_members",
        sa.Column("image_revision_id", sa.String(), primary_key=True),
        sa.Column("assertion_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in (
            "project_id", "proposal_id", "decision_id", "origin_image_revision_id", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "origin_image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "proposal_id", "assertion_id"],
            ["image_reference_assertions.project_id", "image_reference_assertions.proposal_id", "image_reference_assertions.assertion_id"]),
        sa.ForeignKeyConstraint(["project_id", "assertion_id", "decision_id"],
            ["image_link_decisions.project_id", "image_link_decisions.assertion_id", "image_link_decisions.decision_id"]))
    op.execute("CREATE TRIGGER immutable_image_assertion_members BEFORE UPDATE OR DELETE ON image_assertion_members FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT (SELECT count(*) FROM image_revisions WHERE policy_version = 'nasus.image-candidate.v2') + (SELECT count(*) FROM image_assertion_members)")):
        raise RuntimeError("cannot discard frozen review membership")
    op.drop_table("image_assertion_members")
    op.drop_constraint("ck_image_review_membership", "image_revisions", type_="check")
    op.drop_constraint("fk_image_review_parent", "image_revisions", type_="foreignkey")
    for key in ("assertion_count", "parent_artifact_hash", "parent_revision_id"):
        op.drop_column("image_revisions", key)
