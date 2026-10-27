from typing import Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class MappingPartRevisionRecord(Base):
    __tablename__ = "quality_test_design_mapping_part_revisions"
    __table_args__ = (
        UniqueConstraint("project_id", "generation_id", "plan_digest", "sequence", "authority_actor", "revision_sequence"),
        UniqueConstraint("project_id", "generation_id", "plan_digest", "sequence", "authority_actor", "part_revision_id", name="uq_mapping_part_complete_pin"),
        UniqueConstraint("expected_previous_part_revision_id"), UniqueConstraint("invocation_id"),
        Index("uq_mapping_part_first", "project_id", "generation_id", "plan_digest", "sequence", "authority_actor",
            unique=True, postgresql_where=text("expected_previous_part_revision_id IS NULL")),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["project_id", "generation_id"],
            ["quality_test_design_results.project_id", "quality_test_design_results.generation_id"]),
        ForeignKeyConstraint(["project_id", "generation_id", "expected_previous_revision_id"],
            ["quality_test_design_mapping_revisions.project_id", "quality_test_design_mapping_revisions.generation_id", "quality_test_design_mapping_revisions.revision_id"]),
        ForeignKeyConstraint(["project_id", "generation_id", "plan_digest", "sequence", "authority_actor", "expected_previous_part_revision_id"],
            ["quality_test_design_mapping_part_revisions.project_id", "quality_test_design_mapping_part_revisions.generation_id",
             "quality_test_design_mapping_part_revisions.plan_digest", "quality_test_design_mapping_part_revisions.sequence",
             "quality_test_design_mapping_part_revisions.authority_actor", "quality_test_design_mapping_part_revisions.part_revision_id"], name="fk_mapping_part_predecessor"),
        CheckConstraint("sequence >= 0 AND sequence < 65536"),
        CheckConstraint("revision_sequence BETWEEN 1 AND 1000 AND ((revision_sequence = 1 AND expected_previous_part_revision_id IS NULL) OR (revision_sequence > 1 AND expected_previous_part_revision_id IS NOT NULL))"),
    )
    part_revision_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    generation_id: Mapped[str]
    plan_digest: Mapped[str]
    sequence: Mapped[int]
    authority_actor: Mapped[str]
    revision_sequence: Mapped[int]
    expected_previous_revision_id: Mapped[Optional[str]]
    expected_previous_part_revision_id: Mapped[Optional[str]]
    invocation_id: Mapped[str]
    artifact_ref: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
