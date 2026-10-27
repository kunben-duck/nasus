from typing import Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class CaseApprovalRevisionRecord(Base):
    __tablename__ = "quality_case_approval_revisions"
    __table_args__ = (
        UniqueConstraint("cohort_id", "sequence"), UniqueConstraint("invocation_id"), UniqueConstraint("previous_revision_id"),
        UniqueConstraint("project_id", "generation_id", "revision_id"), UniqueConstraint("project_id", "cohort_id", "revision_id"),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["project_id", "generation_id", "mapping_revision_id"],
            ["quality_test_design_mapping_revisions.project_id", "quality_test_design_mapping_revisions.generation_id", "quality_test_design_mapping_revisions.revision_id"]),
        ForeignKeyConstraint(["project_id", "cohort_id", "previous_revision_id"],
            ["quality_case_approval_revisions.project_id", "quality_case_approval_revisions.cohort_id", "quality_case_approval_revisions.revision_id"]),
        CheckConstraint("status IN ('approved', 'withdrawn')"),
        CheckConstraint("sequence BETWEEN 1 AND 1000 AND ((sequence = 1 AND previous_revision_id IS NULL AND status = 'approved') OR (sequence > 1 AND previous_revision_id IS NOT NULL))"),
        Index("uq_case_approval_first", "cohort_id", unique=True, postgresql_where=text("previous_revision_id IS NULL")),
    )
    revision_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    generation_id: Mapped[str]
    mapping_revision_id: Mapped[str]
    cohort_id: Mapped[str] = mapped_column(index=True)
    previous_revision_id: Mapped[Optional[str]]
    sequence: Mapped[int]
    status: Mapped[str]
    invocation_id: Mapped[str]
    artifact_ref: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class CaseApprovalMemberRecord(Base):
    __tablename__ = "quality_case_approval_members"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "generation_id", "revision_id"],
            ["quality_case_approval_revisions.project_id", "quality_case_approval_revisions.generation_id", "quality_case_approval_revisions.revision_id"]),
        ForeignKeyConstraint(["generation_id", "case_id"],
            ["quality_test_design_case_revisions.generation_id", "quality_test_design_case_revisions.case_id"]),
    )
    revision_id: Mapped[str] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    generation_id: Mapped[str]
    case_digest: Mapped[str]
