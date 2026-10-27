from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class MaterializationCommandInputRecord(Base):
    __tablename__ = "materialization_source_inputs"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "manifest_id"],
            ["source_manifests.project_id", "source_manifests.manifest_id"]),
    )

    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("user_identities.user_id"))
    command_hash: Mapped[str]
    manifest_id: Mapped[str]
    manifest_hash: Mapped[str]
    content_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MaterializationLegacyCommandRecord(Base):
    __tablename__ = "materialization_legacy_commands"

    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), primary_key=True)
