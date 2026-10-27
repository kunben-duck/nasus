from typing import Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class AcceptanceRevisionRecord(Base):
    __tablename__ = "quality_acceptance_revisions"
    __table_args__ = (
        UniqueConstraint("ac_id", "sequence"), UniqueConstraint("project_id", "ac_id", "revision_id"),
        UniqueConstraint("previous_revision_id"), UniqueConstraint("invocation_id"),
        Index("uq_acceptance_first", "ac_id", unique=True, postgresql_where=text("previous_revision_id IS NULL")),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        ForeignKeyConstraint(["image_revision_id", "object_id", "document_revision_id"],
            ["image_object_members.image_revision_id", "image_object_members.object_id", "image_object_members.document_revision_id"]),
        ForeignKeyConstraint(["project_id", "binding_id", "source_revision_id", "document_revision_id"],
            ["source_document_revisions.project_id", "source_document_revisions.binding_id", "source_document_revisions.source_revision_id", "source_document_revisions.document_revision_id"]),
        ForeignKeyConstraint(["project_id", "ac_id", "previous_revision_id"],
            ["quality_acceptance_revisions.project_id", "quality_acceptance_revisions.ac_id", "quality_acceptance_revisions.revision_id"]),
        CheckConstraint("status IN ('approved', 'withdrawn')"),
        CheckConstraint("sequence BETWEEN 1 AND 1000 AND ((sequence = 1 AND previous_revision_id IS NULL AND status = 'approved') OR (sequence > 1 AND previous_revision_id IS NOT NULL))"),
    )
    revision_id: Mapped[str] = mapped_column(primary_key=True)
    ac_id: Mapped[str] = mapped_column(index=True)
    project_id: Mapped[str]
    image_revision_id: Mapped[str]
    object_id: Mapped[str]
    binding_id: Mapped[str]
    source_revision_id: Mapped[str]
    document_revision_id: Mapped[str]
    previous_revision_id: Mapped[Optional[str]]
    sequence: Mapped[int]
    status: Mapped[str]
    invocation_id: Mapped[str]
    artifact_ref: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
