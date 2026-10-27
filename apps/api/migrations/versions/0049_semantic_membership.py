"""Freeze reviewed semantic assertions without rewriting v1/v2 artifacts."""
from alembic import op
import sqlalchemy as sa

revision = "0049_semantic_membership"
down_revision = "0048_semantic_reviews"
branch_labels = None
depends_on = None

LEGACY = "(policy_version = 'nasus.image-candidate.v1' AND parent_revision_id IS NULL AND parent_artifact_hash IS NULL AND assertion_count = 0) OR (policy_version = 'nasus.image-candidate.v2' AND parent_revision_id IS NOT NULL AND parent_revision_id <> image_revision_id AND parent_artifact_hash IS NOT NULL AND assertion_count BETWEEN 1 AND 1000)"
SEMANTIC = "(policy_version = 'nasus.image-candidate.v3' AND parent_revision_id IS NOT NULL AND parent_revision_id <> image_revision_id AND parent_artifact_hash IS NOT NULL AND assertion_count BETWEEN 1 AND 1000)"


def upgrade():
    op.drop_constraint("ck_image_review_membership", "image_revisions", type_="check")
    op.create_check_constraint("ck_image_review_membership", "image_revisions", LEGACY + " OR " + SEMANTIC)
    op.create_table("image_semantic_members",
        sa.Column("image_revision_id", sa.String(), primary_key=True),
        sa.Column("claim_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in ("project_id", "assertion_id", "decision_id", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "claim_id", "assertion_id"], ["image_semantic_assertions.project_id", "image_semantic_assertions.claim_id", "image_semantic_assertions.assertion_id"]),
        sa.ForeignKeyConstraint(["project_id", "claim_id", "decision_id"], ["image_semantic_decisions.project_id", "image_semantic_decisions.claim_id", "image_semantic_decisions.decision_id"]))
    op.execute("CREATE TRIGGER immutable_image_semantic_members BEFORE UPDATE OR DELETE ON image_semantic_members FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT (SELECT count(*) FROM image_semantic_members) + (SELECT count(*) FROM image_revisions WHERE policy_version = 'nasus.image-candidate.v3')")):
        raise RuntimeError("cannot discard frozen semantic membership")
    op.drop_table("image_semantic_members")
    op.drop_constraint("ck_image_review_membership", "image_revisions", type_="check")
    op.create_check_constraint("ck_image_review_membership", "image_revisions", LEGACY)
