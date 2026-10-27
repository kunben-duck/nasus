"""Backfill all committed relation facts without rewriting frozen 0072 roots."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

revision = "0073_relation_fact_provenance"
down_revision = "0072_relation_provenance"
branch_labels = None
depends_on = None


def upgrade():
    from apps.api.app.infrastructure.persistence.relation_fact_provenance_v1 import RelationFactProvenanceProjectorV1
    with Session(bind=op.get_bind()) as session:
        RelationFactProvenanceProjectorV1().backfill(session)
        session.commit()


def downgrade():
    if op.get_bind().execute(sa.text("""SELECT EXISTS (
        SELECT 1 FROM image_relation_provenance_nodes
        WHERE kind IN ('reference_proposal', 'reference_assertion', 'reference_decision',
            'semantic_evaluation', 'semantic_assertion', 'semantic_decision'))""")).scalar():
        raise RuntimeError("Cannot discard registered relation fact provenance.")
