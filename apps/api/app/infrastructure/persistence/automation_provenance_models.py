from typing import Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class AutomationProvenanceRecord(Base):
    __tablename__ = "quality_automation_provenance"
    __table_args__ = (
        UniqueConstraint("project_id", "context_id", "node_key", "content_hash", name="uq_automation_provenance_pin"),
        ForeignKeyConstraint(["project_id", "context_id"],
            ["system_image_context_packs.project_id", "system_image_context_packs.context_id"]),
        ForeignKeyConstraint(["project_id", "script_revision_id"],
            ["quality_automation_script_revisions.project_id", "quality_automation_script_revisions.script_revision_id"]),
        ForeignKeyConstraint(["project_id", "script_revision_id", "review_revision_id"],
            ["quality_automation_script_reviews.project_id", "quality_automation_script_reviews.script_revision_id",
             "quality_automation_script_reviews.revision_id"]),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        CheckConstraint("(kind = 'script' AND review_revision_id IS NULL AND artifact_id = script_revision_id) OR "
            "(kind = 'script_review' AND review_revision_id IS NOT NULL AND artifact_id = review_revision_id)"),
        CheckConstraint("node_key = kind || ':' || artifact_id"),
        CheckConstraint("policy_revision = 'nasus.automation-provenance.v1'"),
        Index("ix_automation_provenance_context", "project_id", "context_id", "kind", "artifact_id"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    node_key: Mapped[str] = mapped_column(primary_key=True)
    context_id: Mapped[str]
    kind: Mapped[str]
    artifact_id: Mapped[str]
    artifact_hash: Mapped[str]
    invocation_id: Mapped[str]
    script_revision_id: Mapped[str]
    review_revision_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    policy_revision: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class AutomationProvenanceEdgeRecord(Base):
    __tablename__ = "quality_automation_provenance_edges"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "context_id", "node_key", "node_hash"],
            ["quality_automation_provenance.project_id", "quality_automation_provenance.context_id",
             "quality_automation_provenance.node_key", "quality_automation_provenance.content_hash"]),
        ForeignKeyConstraint(["project_id", "context_id", "test_design_key", "parent_hash"],
            ["system_image_derivations.project_id", "system_image_derivations.context_id",
             "system_image_derivations.node_key", "system_image_derivations.content_hash"]),
        ForeignKeyConstraint(["project_id", "context_id", "automation_key", "parent_hash"],
            ["quality_automation_provenance.project_id", "quality_automation_provenance.context_id",
             "quality_automation_provenance.node_key", "quality_automation_provenance.content_hash"]),
        CheckConstraint("(test_design_key = parent_key AND automation_key IS NULL) OR "
            "(automation_key = parent_key AND test_design_key IS NULL)"),
        CheckConstraint("test_design_key IS NOT NULL OR automation_key IS NOT NULL"),
        CheckConstraint("node_key <> parent_key"),
        Index("ix_automation_provenance_parent", "project_id", "parent_key", "node_key"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    node_key: Mapped[str] = mapped_column(primary_key=True)
    parent_key: Mapped[str] = mapped_column(primary_key=True)
    context_id: Mapped[str]
    node_hash: Mapped[str]
    parent_hash: Mapped[str]
    parent_artifact_hash: Mapped[str]
    test_design_key: Mapped[Optional[str]] = mapped_column(nullable=True)
    automation_key: Mapped[Optional[str]] = mapped_column(nullable=True)
