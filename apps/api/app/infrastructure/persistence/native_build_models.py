from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class NativeBuildReservationRecord(Base):
    __tablename__ = "quality_native_build_reservations"
    __table_args__ = (
        UniqueConstraint("project_id", "invocation_id", "build_id"), UniqueConstraint("build_id"),
        UniqueConstraint("project_id", "invocation_id", "build_id", "image_revision_id", "manifest_id", "binding_id", "source_revision_id",
            name="uq_native_build_binding_source"),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        ForeignKeyConstraint(["project_id", "image_revision_id", "manifest_id"],
            ["image_revisions.project_id", "image_revisions.image_revision_id", "image_revisions.manifest_id"]),
        ForeignKeyConstraint(["project_id", "manifest_id", "binding_id", "source_revision_id"],
            ["source_manifest_members.project_id", "source_manifest_members.manifest_id",
             "source_manifest_members.binding_id", "source_manifest_members.source_revision_id"]),
        CheckConstraint("worker_epoch >= 1"),
    )
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    build_id: Mapped[str]
    image_revision_id: Mapped[str]
    manifest_id: Mapped[str]
    binding_id: Mapped[str]
    source_revision_id: Mapped[str]
    actor_id: Mapped[str]
    worker_owner: Mapped[str]
    worker_epoch: Mapped[int]
    request_hash: Mapped[str]
    recorded_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class NativeBuildResultRecord(Base):
    __tablename__ = "quality_native_build_results"
    __table_args__ = (
        UniqueConstraint("project_id", "invocation_id"), UniqueConstraint("build_id"),
        UniqueConstraint("project_id", "invocation_id", "build_id", "artifact_hash", "receipt_digest",
            name="uq_native_build_binding_parent"),
        ForeignKeyConstraint(["project_id", "invocation_id", "build_id"],
            ["quality_native_build_reservations.project_id", "quality_native_build_reservations.invocation_id",
             "quality_native_build_reservations.build_id"]),
    )
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    build_id: Mapped[str]
    artifact_ref: Mapped[str]
    artifact_hash: Mapped[str]
    receipt_digest: Mapped[str]
    recorded_at: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class NativeBuildWorkLeaseRecord(Base):
    __tablename__ = "quality_native_build_work_leases"
    __table_args__ = (ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]), CheckConstraint("epoch >= 1"))
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    owner_id: Mapped[str]
    epoch: Mapped[int]
    request_digest: Mapped[str]
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    renewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NativeBuildCancellationRecord(Base):
    __tablename__ = "quality_native_build_cancellations"
    __table_args__ = (ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),)
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
