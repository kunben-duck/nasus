from sqlalchemy import JSON, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class ImageSemanticMemberRecord(Base):
    __tablename__ = "image_semantic_members"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        ForeignKeyConstraint(["project_id", "claim_id", "assertion_id"], ["image_semantic_assertions.project_id", "image_semantic_assertions.claim_id", "image_semantic_assertions.assertion_id"]),
        ForeignKeyConstraint(["project_id", "claim_id", "decision_id"], ["image_semantic_decisions.project_id", "image_semantic_decisions.claim_id", "image_semantic_decisions.decision_id"]),
    )
    image_revision_id: Mapped[str] = mapped_column(primary_key=True)
    claim_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    assertion_id: Mapped[str]
    decision_id: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
