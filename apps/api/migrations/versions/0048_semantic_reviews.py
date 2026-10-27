"""Pin typed semantic assertions and append reviewer decisions per frozen claim."""
from alembic import op
import sqlalchemy as sa

revision = "0048_semantic_reviews"
down_revision = "0047_semantic_evaluations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_semantic_evaluation_project", "image_semantic_evaluations", ["project_id", "invocation_id"])
    op.create_table("image_semantic_assertions",
        sa.Column("assertion_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in ("project_id", "claim_id", "evaluation_id", "image_revision_id", "subject_object_id", "object_id", "predicate", "content_hash")],
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("project_id", "claim_id", "assertion_id"),
        sa.ForeignKeyConstraint(["project_id", "evaluation_id"], ["image_semantic_evaluations.project_id", "image_semantic_evaluations.invocation_id"]),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        sa.ForeignKeyConstraint(["image_revision_id", "subject_object_id"], ["image_object_members.image_revision_id", "image_object_members.object_id"]),
        sa.ForeignKeyConstraint(["image_revision_id", "object_id"], ["image_object_members.image_revision_id", "image_object_members.object_id"]),
        sa.CheckConstraint("predicate IN ('implements', 'asserts')"))
    op.create_index("ix_image_semantic_assertions_claim_id", "image_semantic_assertions", ["claim_id"])
    op.create_table("image_semantic_decisions",
        sa.Column("decision_id", sa.String(), primary_key=True),
        *[sa.Column(key, sa.String(), nullable=False) for key in ("project_id", "claim_id", "assertion_id", "invocation_id", "content_hash")],
        sa.Column("previous_decision_id", sa.String()), sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("invocation_id"), sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.UniqueConstraint("claim_id", "sequence"), sa.UniqueConstraint("project_id", "claim_id", "decision_id"), sa.UniqueConstraint("previous_decision_id"),
        sa.ForeignKeyConstraint(["project_id", "claim_id", "assertion_id"], ["image_semantic_assertions.project_id", "image_semantic_assertions.claim_id", "image_semantic_assertions.assertion_id"]),
        sa.ForeignKeyConstraint(["project_id", "claim_id", "previous_decision_id"], ["image_semantic_decisions.project_id", "image_semantic_decisions.claim_id", "image_semantic_decisions.decision_id"]),
        sa.CheckConstraint("sequence BETWEEN 1 AND 1000 AND ((sequence = 1 AND previous_decision_id IS NULL) OR (sequence > 1 AND previous_decision_id IS NOT NULL))"))
    op.create_index("uq_semantic_review_first", "image_semantic_decisions", ["claim_id"], unique=True, postgresql_where=sa.text("previous_decision_id IS NULL"))
    for table in ("image_semantic_assertions", "image_semantic_decisions"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM image_semantic_assertions")):
        raise RuntimeError("cannot downgrade while semantic reviews exist")
    op.drop_table("image_semantic_decisions")
    op.drop_table("image_semantic_assertions")
    op.drop_constraint("uq_semantic_evaluation_project", "image_semantic_evaluations", type_="unique")
