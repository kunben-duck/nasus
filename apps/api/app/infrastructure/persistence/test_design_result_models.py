from typing import Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class TestDesignResultRecord(Base):
    __test__ = False
    __tablename__ = "quality_test_design_results"
    __table_args__ = (
        UniqueConstraint("invocation_id"), UniqueConstraint("call_id"),
        UniqueConstraint("project_id", "generation_id"),
        UniqueConstraint("generation_id", "invocation_id", name="uq_test_design_result_invocation_pin"),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["call_id"], ["llm_calls.id"]),
        ForeignKeyConstraint(["scope_revision_id"], ["quality_test_design_scope_revisions.revision_id"]),
        CheckConstraint("status = 'draft'"),
        CheckConstraint("(provenance_kind = 'single' AND call_id IS NOT NULL) OR (provenance_kind = 'batch' AND call_id IS NULL)", name="ck_test_design_result_call_kind"),
    )
    generation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    scope_revision_id: Mapped[str]
    invocation_id: Mapped[str]
    call_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    provenance_kind: Mapped[str] = mapped_column(default="single", server_default="single")
    status: Mapped[str]
    artifact_ref: Mapped[str]
    artifact_hash: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class TestDesignCaseRecord(Base):
    __test__ = False
    __tablename__ = "quality_test_design_case_revisions"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "generation_id"], ["quality_test_design_results.project_id", "quality_test_design_results.generation_id"]),
    )
    generation_id: Mapped[str] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class TestDesignCoverageRecord(Base):
    __test__ = False
    __tablename__ = "quality_test_design_coverage"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "generation_id"], ["quality_test_design_results.project_id", "quality_test_design_results.generation_id"]),
    )
    generation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class TestDesignResultBatchCallRecord(Base):
    __test__ = False
    __tablename__ = "quality_test_design_result_batch_calls"
    __table_args__ = (
        UniqueConstraint("generation_id", "call_id"),
        ForeignKeyConstraint(["project_id", "generation_id"], ["quality_test_design_results.project_id", "quality_test_design_results.generation_id"]),
        ForeignKeyConstraint(["generation_id", "invocation_id"], ["quality_test_design_results.generation_id", "quality_test_design_results.invocation_id"]),
        ForeignKeyConstraint(["invocation_id", "sequence", "call_id"], ["quality_test_design_batch_replies.invocation_id", "quality_test_design_batch_replies.sequence", "quality_test_design_batch_replies.call_id"]),
        CheckConstraint("sequence >= 0 AND sequence < 64", name="ck_test_design_result_batch_sequence"),
    )
    generation_id: Mapped[str] = mapped_column(primary_key=True)
    sequence: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    invocation_id: Mapped[str]
    call_id: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
