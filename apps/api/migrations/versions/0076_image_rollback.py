"""Explicit rollback source pins; preserve existing publication payloads and hashes."""
from alembic import op
import sqlalchemy as sa

revision = "0076_image_rollback"
down_revision = "0075_context_authorities"
branch_labels = None
depends_on = None


def upgrade():
    for table, constraint in (("image_publication_reviews", "fk_publication_review_rollback"),
                              ("image_publications", "fk_publication_rollback")):
        op.add_column(table, sa.Column("rollback_publication_id", sa.String(), nullable=True))
        op.create_foreign_key(constraint, table, "image_publications",
            ["project_id", "baseline_id", "rollback_publication_id"], ["project_id", "baseline_id", "publication_id"])


def downgrade():
    for table in ("image_publication_reviews", "image_publications"):
        if op.get_bind().execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE rollback_publication_id IS NOT NULL)")).scalar():
            raise RuntimeError("Cannot discard recorded image rollback pins.")
    for table, constraint in (("image_publication_reviews", "fk_publication_review_rollback"),
                              ("image_publications", "fk_publication_rollback")):
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.drop_column(table, "rollback_publication_id")
