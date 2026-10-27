"""Append-only linkage between a failed generation and its recovery command."""
from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class GenerationBatchRecoveryResultRecord(Base):
    __tablename__ = "quality_test_design_batch_recovery_results"
    __table_args__ = (
        UniqueConstraint("authority_invocation_id"),
        ForeignKeyConstraint(["project_id", "generation_id"],
            ["quality_test_design_results.project_id", "quality_test_design_results.generation_id"]),
        ForeignKeyConstraint(["generation_id", "source_invocation_id"],
            ["quality_test_design_results.generation_id", "quality_test_design_results.invocation_id"]),
        ForeignKeyConstraint(["authority_invocation_id"], ["tool_invocations.id"]),
        CheckConstraint("source_invocation_id <> authority_invocation_id", name="ck_batch_recovery_distinct_authority"),
    )
    generation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    source_invocation_id: Mapped[str]
    authority_invocation_id: Mapped[str]
    artifact_hash: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
