from typing import Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class AutomationScriptReviewRecord(Base):
    __tablename__ = "quality_automation_script_reviews"
    __table_args__ = (
        UniqueConstraint("script_revision_id", "sequence"),
        UniqueConstraint("project_id", "script_revision_id", "revision_id"),
        UniqueConstraint("previous_revision_id"), UniqueConstraint("invocation_id"),
        Index("uq_script_review_first", "script_revision_id", unique=True,
            postgresql_where=text("previous_revision_id IS NULL")),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["project_id", "script_revision_id"],
            ["quality_automation_script_revisions.project_id", "quality_automation_script_revisions.script_revision_id"]),
        ForeignKeyConstraint(["project_id", "script_revision_id", "previous_revision_id"],
            ["quality_automation_script_reviews.project_id", "quality_automation_script_reviews.script_revision_id",
             "quality_automation_script_reviews.revision_id"]),
        CheckConstraint("status IN ('reviewed', 'withdrawn')"),
        CheckConstraint("sequence BETWEEN 1 AND 1000 AND ((sequence = 1 AND previous_revision_id IS NULL AND status = 'reviewed') OR (sequence > 1 AND previous_revision_id IS NOT NULL))"),
    )
    revision_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    script_revision_id: Mapped[str] = mapped_column(index=True)
    previous_revision_id: Mapped[Optional[str]]
    sequence: Mapped[int]
    status: Mapped[str]
    invocation_id: Mapped[str]
    artifact_ref: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
