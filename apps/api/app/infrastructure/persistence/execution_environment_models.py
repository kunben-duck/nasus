"""Dedicated M3 lifecycle tables; imported by the composition root, not vice versa."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class ExecutionEnvironmentRecord(Base):
    __tablename__ = "quality_execution_environments"
    __table_args__ = (
        CheckConstraint("generation BETWEEN 0 AND 9007199254740991"),
        CheckConstraint("max_snapshot_bytes BETWEEN 1 AND 16777216"),
        CheckConstraint("state IN ('available', 'leased', 'quarantined')"),
        CheckConstraint("(state = 'available' AND active_lease_id IS NULL) OR "
                        "(state <> 'available' AND active_lease_id IS NOT NULL)"),
    )
    environment_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128))
    target_key: Mapped[str] = mapped_column(String(128), unique=True)
    inventory_hash: Mapped[str] = mapped_column(String(71))
    max_snapshot_bytes: Mapped[int]
    generation: Mapped[int] = mapped_column(BigInteger, default=0)
    state: Mapped[str] = mapped_column(String(32), default="available")
    active_lease_id: Mapped[Optional[str]] = mapped_column(String(128))


class ExecutionEnvironmentLeaseRecord(Base):
    __tablename__ = "quality_execution_environment_leases"
    __table_args__ = (
        UniqueConstraint("environment_id", "generation"),
        UniqueConstraint("lease_id", "generation"),
        CheckConstraint("generation BETWEEN 1 AND 9007199254740991"),
        CheckConstraint("expires_at > created_at AND expires_at <= created_at + interval '900 seconds'"),
        CheckConstraint("phase IN ('leased', 'capturing_before', 'before_ready', 'running', 'stopping', 'stopped', "
                        "'capturing_after', 'after_ready', 'resetting', 'reset_complete', 'released', 'quarantined')"),
        CheckConstraint("phase NOT IN ('before_ready', 'stopped', 'capturing_after', 'after_ready', 'resetting', 'reset_complete') "
                        "OR stopped_proof_id IS NOT NULL"),
        CheckConstraint("NOT baseline_verified OR baseline_proof_id IS NOT NULL"),
        CheckConstraint("phase IN ('leased', 'capturing_before', 'released', 'quarantined') OR baseline_verified"),
        CheckConstraint("NOT reset_verified OR reset_proof_id IS NOT NULL"),
        CheckConstraint("phase <> 'reset_complete' OR reset_verified"),
        Index("uq_execution_environment_active_lease", "environment_id", unique=True,
              postgresql_where=text("phase <> 'released'")),
    )
    lease_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    environment_id: Mapped[str] = mapped_column(ForeignKey("quality_execution_environments.environment_id"))
    version_id: Mapped[str] = mapped_column(String(128))
    batch_id: Mapped[str] = mapped_column(String(128))
    owner_id: Mapped[str] = mapped_column(String(128))
    generation: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    phase: Mapped[str] = mapped_column(String(32))
    stopped_proof_id: Mapped[Optional[str]] = mapped_column(String(128))
    baseline_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    baseline_proof_id: Mapped[Optional[str]] = mapped_column(String(128))
    reset_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    reset_proof_id: Mapped[Optional[str]] = mapped_column(String(128))
    quarantine_reason: Mapped[Optional[str]] = mapped_column(String(32))


class ExecutionEnvironmentSnapshotRecord(Base):
    __tablename__ = "quality_execution_environment_snapshots"
    __table_args__ = (
        UniqueConstraint("lease_id", "phase"),
        UniqueConstraint("snapshot_id", "lease_id", "generation", "phase", "content_hash"),
        ForeignKeyConstraint(["lease_id", "generation"],
            ["quality_execution_environment_leases.lease_id", "quality_execution_environment_leases.generation"]),
        CheckConstraint("phase IN ('before', 'after')"),
        CheckConstraint("size_bytes BETWEEN 1 AND 16777216"),
        CheckConstraint("storage_readback_verified"),
        CheckConstraint("NOT snapshot_verified OR snapshot_proof_id IS NOT NULL"),
        CheckConstraint("NOT restore_verified"),
    )
    snapshot_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    lease_id: Mapped[str] = mapped_column(String(128))
    generation: Mapped[int] = mapped_column(BigInteger)
    phase: Mapped[str] = mapped_column(String(8))
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    content_hash: Mapped[str] = mapped_column(String(71))
    encrypted_hash: Mapped[str] = mapped_column(String(71))
    size_bytes: Mapped[int]
    storage_readback_verified: Mapped[bool] = mapped_column(Boolean)
    snapshot_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    snapshot_proof_id: Mapped[Optional[str]] = mapped_column(String(128))
    restore_verified: Mapped[bool] = mapped_column(Boolean, default=False)


class ExecutionEnvironmentSnapshotRestoreRecord(Base):
    """Append-only independent-copy proof; source baseline reset is a separate fact."""
    __tablename__ = "quality_execution_snapshot_restores"
    __table_args__ = (
        ForeignKeyConstraint(["snapshot_id", "lease_id", "generation", "phase", "content_hash"],
            ["quality_execution_environment_snapshots." + key for key in
             ("snapshot_id", "lease_id", "generation", "phase", "content_hash")]),
        CheckConstraint("verified AND independent_copy_verified AND source_unchanged"),
    )
    snapshot_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    lease_id: Mapped[str] = mapped_column(String(128))
    generation: Mapped[int] = mapped_column(BigInteger)
    phase: Mapped[str] = mapped_column(String(8))
    content_hash: Mapped[str] = mapped_column(String(71))
    proof_id: Mapped[str] = mapped_column(String(128), unique=True)
    independent_target_key: Mapped[str] = mapped_column(String(128))
    verified: Mapped[bool] = mapped_column(Boolean)
    independent_copy_verified: Mapped[bool] = mapped_column(Boolean)
    source_unchanged: Mapped[bool] = mapped_column(Boolean)
