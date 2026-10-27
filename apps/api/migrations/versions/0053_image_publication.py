"""Immutable image publication reviews and CAS baseline heads."""
from alembic import op
import sqlalchemy as sa

revision = "0053_image_publication"
down_revision = "0052_business_rule_authority"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_baseline_project_id", "baselines", ["project_id", "id"])
    op.create_table("image_publication_reviews",
        sa.Column("review_id", sa.String(), primary_key=True),
        *[sa.Column(k, sa.String(), nullable=False) for k in ("project_id", "baseline_id", "image_revision_id", "claim_digest", "invocation_id", "request_hash", "content_hash")],
        sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("project_id", "review_id"), sa.UniqueConstraint("claim_digest", "sequence"), sa.UniqueConstraint("invocation_id"),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "baseline_id"], ["baselines.project_id", "baselines.id"]),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]), sa.CheckConstraint("sequence > 0"))
    op.create_index("ix_image_publication_reviews_claim_digest", "image_publication_reviews", ["claim_digest"])
    op.create_table("image_publications",
        sa.Column("publication_id", sa.String(), primary_key=True),
        *[sa.Column(k, sa.String(), nullable=False) for k in ("project_id", "baseline_id", "image_revision_id", "approval_id", "invocation_id", "request_hash", "content_hash")],
        sa.Column("previous_publication_id", sa.String()), sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("project_id", "baseline_id", "publication_id"), sa.UniqueConstraint("project_id", "baseline_id", "sequence"), sa.UniqueConstraint("invocation_id"),
        sa.ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        sa.ForeignKeyConstraint(["project_id", "baseline_id"], ["baselines.project_id", "baselines.id"]),
        sa.ForeignKeyConstraint(["project_id", "approval_id"], ["image_publication_reviews.project_id", "image_publication_reviews.review_id"]),
        sa.ForeignKeyConstraint(["project_id", "baseline_id", "previous_publication_id"], ["image_publications.project_id", "image_publications.baseline_id", "image_publications.publication_id"]),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        sa.CheckConstraint("(sequence = 1 AND previous_publication_id IS NULL) OR (sequence > 1 AND previous_publication_id IS NOT NULL)"))
    op.create_table("image_publication_heads",
        sa.Column("project_id", sa.String(), primary_key=True), sa.Column("baseline_id", sa.String(), primary_key=True),
        sa.Column("publication_id", sa.String(), nullable=False), sa.Column("sequence", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "baseline_id", "publication_id"], ["image_publications.project_id", "image_publications.baseline_id", "image_publications.publication_id"]),
        sa.CheckConstraint("sequence > 0"))
    for table in ("image_publication_reviews", "image_publications"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION nasus_reject_image_revision_mutation()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM image_publication_reviews")):
        raise RuntimeError("cannot downgrade while publication reviews exist")
    for table in ("image_publication_heads", "image_publications", "image_publication_reviews"):
        op.drop_table(table)
    op.drop_constraint("uq_baseline_project_id", "baselines", type_="unique")
