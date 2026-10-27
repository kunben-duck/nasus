from typing import Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class TestDesignScopeRecord(Base):
    __test__ = False
    __tablename__ = "quality_test_design_scope_revisions"
    __table_args__ = (
        UniqueConstraint("scope_id", "sequence"), UniqueConstraint("project_id", "scope_id", "revision_id"),
        UniqueConstraint("previous_revision_id"), UniqueConstraint("invocation_id"),
        Index("uq_test_design_scope_first", "scope_id", unique=True, postgresql_where=text("previous_revision_id IS NULL")),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["context_id"], ["system_image_context_packs.context_id"]),
        ForeignKeyConstraint(["project_id", "scope_id", "previous_revision_id"],
            ["quality_test_design_scope_revisions.project_id", "quality_test_design_scope_revisions.scope_id", "quality_test_design_scope_revisions.revision_id"]),
        CheckConstraint("status IN ('approved', 'withdrawn')"),
        CheckConstraint("sequence BETWEEN 1 AND 1000 AND ((sequence = 1 AND previous_revision_id IS NULL AND status = 'approved') OR (sequence > 1 AND previous_revision_id IS NOT NULL))"),
    )
    revision_id: Mapped[str] = mapped_column(primary_key=True)
    scope_id: Mapped[str] = mapped_column(index=True)
    project_id: Mapped[str]
    context_id: Mapped[str]
    previous_revision_id: Mapped[Optional[str]]
    sequence: Mapped[int]
    status: Mapped[str]
    invocation_id: Mapped[str]
    artifact_ref: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
