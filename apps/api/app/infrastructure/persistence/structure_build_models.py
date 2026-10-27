from typing import Optional

from sqlalchemy import ForeignKey, ForeignKeyConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class StructureBuildArtifactRecord(Base):
    __tablename__ = "image_structure_build_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "plan_id"], ["image_build_plans.project_id", "image_build_plans.plan_id"]),
        ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
    )
    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    plan_id: Mapped[str]
    plan_digest: Mapped[str]
    target_baseline_id: Mapped[str]
    target_version_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    image_revision_id: Mapped[str]
    executor_version: Mapped[str]
    confirmed_at: Mapped[str]
    lineage_required: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
