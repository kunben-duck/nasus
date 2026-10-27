from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class HttpFixtureRecipeRecord(Base):
    __tablename__ = "quality_http_fixture_recipes"
    __table_args__ = (
        UniqueConstraint("project_id", "record_id"), UniqueConstraint("invocation_id"),
        UniqueConstraint("project_id", "record_id", "artifact_hash", name="uq_http_fixture_recipe_original"),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "image_revision_id", "manifest_id"],
            ["quality_run_plans.project_id", "quality_run_plans.run_plan_id", "quality_run_plans.artifact_hash",
             "quality_run_plans.plan_digest", "quality_run_plans.image_revision_id", "quality_run_plans.manifest_id"]),
        CheckConstraint("status = 'recorded'"),
        Index("ix_http_fixture_recipe_history", "project_id", "run_plan_id", "case_id", "record_id"),
    )
    record_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    run_plan_id: Mapped[str]
    run_plan_artifact_hash: Mapped[str]
    plan_digest: Mapped[str]
    image_revision_id: Mapped[str]
    image_artifact_hash: Mapped[str]
    manifest_id: Mapped[str]
    manifest_hash: Mapped[str]
    case_id: Mapped[str]
    data_manifest_hash: Mapped[str]
    fixture_digest: Mapped[str]
    invocation_id: Mapped[str]
    actor_id: Mapped[str]
    recorded_at: Mapped[str]
    artifact_ref: Mapped[str]
    artifact_hash: Mapped[str]
    request_hash: Mapped[str]
    status: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]
