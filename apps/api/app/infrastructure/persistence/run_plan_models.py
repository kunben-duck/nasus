from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class RunPlanRecord(Base):
    __tablename__ = "quality_run_plans"
    __table_args__ = (
        UniqueConstraint("project_id", "run_plan_id"), UniqueConstraint("invocation_id"),
        UniqueConstraint("project_id", "run_plan_id", "artifact_hash", "plan_digest", "image_revision_id", "manifest_id",
            name="uq_run_plan_build_parent"),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["project_id", "context_id"],
            ["system_image_context_packs.project_id", "system_image_context_packs.context_id"]),
        ForeignKeyConstraint(["project_id", "image_revision_id", "manifest_id"],
            ["image_revisions.project_id", "image_revisions.image_revision_id", "image_revisions.manifest_id"]),
        ForeignKeyConstraint(["project_id", "script_revision_id", "review_revision_id"],
            ["quality_automation_script_reviews.project_id", "quality_automation_script_reviews.script_revision_id",
             "quality_automation_script_reviews.revision_id"]),
        ForeignKeyConstraint(["project_id", "context_id", "script_node_key", "script_node_hash"],
            ["quality_automation_provenance.project_id", "quality_automation_provenance.context_id",
             "quality_automation_provenance.node_key", "quality_automation_provenance.content_hash"]),
        ForeignKeyConstraint(["project_id", "context_id", "review_node_key", "review_node_hash"],
            ["quality_automation_provenance.project_id", "quality_automation_provenance.context_id",
             "quality_automation_provenance.node_key", "quality_automation_provenance.content_hash"]),
        CheckConstraint("status = 'prepared'"),
        CheckConstraint("script_node_key = 'script:' || script_revision_id AND review_node_key = 'script_review:' || review_revision_id"),
        Index("ix_run_plan_script", "project_id", "script_revision_id", "run_plan_id"),
    )
    run_plan_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    context_id: Mapped[str]
    image_revision_id: Mapped[str]
    manifest_id: Mapped[str]
    script_revision_id: Mapped[str]
    review_revision_id: Mapped[str]
    script_node_key: Mapped[str]
    script_node_hash: Mapped[str]
    review_node_key: Mapped[str]
    review_node_hash: Mapped[str]
    invocation_id: Mapped[str]
    artifact_ref: Mapped[str]
    artifact_hash: Mapped[str]
    request_hash: Mapped[str]
    plan_digest: Mapped[str]
    status: Mapped[str]
    actor_id: Mapped[str]
    recorded_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
