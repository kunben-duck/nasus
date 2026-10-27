from sqlalchemy import ForeignKey, ForeignKeyConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class StructureBuildLineageRecord(Base):
    __tablename__ = "image_structure_build_lineages"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "image_revision_id"],
            ["image_revisions.project_id", "image_revisions.image_revision_id"]),
    )
    invocation_id: Mapped[str] = mapped_column(ForeignKey("image_structure_build_artifacts.invocation_id"), primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    image_revision_id: Mapped[str]
    lineage_hash: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSONB)
