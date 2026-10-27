from sqlalchemy import JSON, CheckConstraint, ForeignKey, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class BuildPlanRecord(Base):
    __tablename__ = "image_build_plans"
    __table_args__ = (
        UniqueConstraint("project_id", "plan_id"),
        UniqueConstraint("project_id", "plan_digest"),
        ForeignKeyConstraint(["project_id", "manifest_id"], ["source_manifests.project_id", "source_manifests.manifest_id"]),
        CheckConstraint("state = 'draft'"),
    )
    plan_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    manifest_id: Mapped[str]
    plan_digest: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str]
    created_by: Mapped[str]
    state: Mapped[str]


class BuildPlanInvocationRecord(Base):
    __tablename__ = "image_build_plan_invocations"
    __table_args__ = (ForeignKeyConstraint(["project_id", "plan_id"], ["image_build_plans.project_id", "image_build_plans.plan_id"]),)
    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), primary_key=True)
    project_id: Mapped[str]
    plan_id: Mapped[str]
