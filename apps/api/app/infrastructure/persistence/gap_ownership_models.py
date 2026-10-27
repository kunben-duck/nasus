from __future__ import annotations
from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class BuildGapOwnershipRecord(Base):
    __tablename__ = "image_build_gap_ownership_revisions"
    __table_args__ = (
        UniqueConstraint("project_id", "completion_invocation_id", "revision_id", "revision_hash"),
        UniqueConstraint("completion_invocation_id", "revision_number"),
        ForeignKeyConstraint(["project_id", "completion_invocation_id", "parent_revision_id", "parent_revision_hash"],
            ["image_build_gap_ownership_revisions.project_id", "image_build_gap_ownership_revisions.completion_invocation_id",
             "image_build_gap_ownership_revisions.revision_id", "image_build_gap_ownership_revisions.revision_hash"]),
        CheckConstraint("revision_number BETWEEN 1 AND 80"),
        CheckConstraint("(revision_number = 1 AND parent_revision_id IS NULL AND parent_revision_hash IS NULL) OR (revision_number > 1 AND parent_revision_id IS NOT NULL AND parent_revision_hash IS NOT NULL)"),
    )
    revision_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    completion_invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), index=True)
    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), unique=True)
    parent_revision_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    parent_revision_hash: Mapped[Optional[str]] = mapped_column(nullable=True)
    revision_number: Mapped[int]
    revision_hash: Mapped[str]
    request_payload: Mapped[dict] = mapped_column(JSON)
    confirmed_by: Mapped[str] = mapped_column(ForeignKey("user_identities.user_id"))
    created_at: Mapped[str]
