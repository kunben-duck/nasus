from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class SourceAcquisitionIntentRecord(Base):
    __tablename__ = "source_acquisition_intents"
    __table_args__ = (
        UniqueConstraint("project_id", "invocation_id", name="uq_source_acquisition_project_command"),
        ForeignKeyConstraint(["project_id", "origin_manifest_id"],
            ["source_manifests.project_id", "source_manifests.manifest_id"]),
        CheckConstraint("selection_mode IN ('selected', 'whole_project')", name="ck_source_acquisition_mode"),
        CheckConstraint("(origin_manifest_id IS NULL) = (origin_manifest_hash IS NULL)", name="ck_source_acquisition_origin"),
    )

    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("user_identities.user_id"))
    command_hash: Mapped[str]
    selection_mode: Mapped[str]
    sources: Mapped[list] = mapped_column(JSON)
    origin_manifest_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    origin_manifest_hash: Mapped[Optional[str]] = mapped_column(nullable=True)
    content_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
