from sqlalchemy import JSON, ForeignKey, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class SemanticCallReservationRecord(Base):
    __tablename__ = "image_semantic_call_reservations"
    __table_args__ = (
        UniqueConstraint("project_id", "invocation_id"),
        ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
    )
    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), primary_key=True)
    project_id: Mapped[str]
    image_revision_id: Mapped[str]
    content_hash: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)


class SemanticEvaluationRecord(Base):
    __tablename__ = "image_semantic_evaluations"
    __table_args__ = (UniqueConstraint("project_id", "invocation_id", name="uq_semantic_evaluation_project"), ForeignKeyConstraint(["project_id", "invocation_id"],
        ["image_semantic_call_reservations.project_id", "image_semantic_call_reservations.invocation_id"]),)
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    artifact_ref: Mapped[str]
    artifact_hash: Mapped[str]
