from __future__ import annotations

from sqlalchemy import JSON, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class VersionCreationRecord(Base):
    __tablename__ = "version_creations"
    __table_args__ = (
        UniqueConstraint("project_id", "version_id"),
        ForeignKeyConstraint(["project_id", "version_id"], ["versions.project_id", "versions.id"]),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
    )
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    version_id: Mapped[str] = mapped_column(unique=True)
    actor_id: Mapped[str]
    request_hash: Mapped[str]
    created_at: Mapped[str]


class VersionImageBindingRecord(Base):
    __tablename__ = "version_image_bindings"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "version_id"], ["version_creations.project_id", "version_creations.version_id"]),
        ForeignKeyConstraint(["project_id", "baseline_id", "publication_id"],
            ["image_publications.project_id", "image_publications.baseline_id", "image_publications.publication_id"]),
        ForeignKeyConstraint(["project_id", "image_revision_id"],
            ["image_revisions.project_id", "image_revisions.image_revision_id"]),
    )
    version_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    baseline_id: Mapped[str]
    publication_id: Mapped[str]
    image_revision_id: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class ProjectDeliveryRecord(Base):
    __tablename__ = "project_delivery"
    __table_args__ = (ForeignKeyConstraint(["project_id", "enabled_by_version_id"],
        ["version_creations.project_id", "version_creations.version_id"]),)
    project_id: Mapped[str] = mapped_column(primary_key=True)
    enabled_by_version_id: Mapped[str]
    enabled_at: Mapped[str]
