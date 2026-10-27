from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class CodeIndexGenerationRecord(Base):
    __tablename__ = "code_index_generations"
    __table_args__ = (
        UniqueConstraint("project_id", "generation_id"),
        UniqueConstraint("source_revision_id", "provider_fingerprint", "invocation_id"),
        UniqueConstraint("invocation_id", "binding_id", name="uq_code_index_command_binding"),
        ForeignKeyConstraint(["project_id", "binding_id", "source_revision_id"],
            ["source_revisions.project_id", "source_revisions.binding_id", "source_revisions.source_revision_id"]),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
    )
    generation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    binding_id: Mapped[str]
    source_revision_id: Mapped[str]
    source_manifest_hash: Mapped[str]
    snapshot_hash: Mapped[str]
    provider_fingerprint: Mapped[str]
    invocation_id: Mapped[str]
    content_hash: Mapped[str]


class CodeIndexWorkerLeaseRecord(Base):
    __tablename__ = "code_index_worker_leases"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "generation_id"],
            ["code_index_generations.project_id", "code_index_generations.generation_id"]),
        CheckConstraint("epoch >= 0"),
        CheckConstraint("state IN ('idle', 'preparing', 'ready', 'degraded', 'cancel_requested', 'cancelled', 'failed')"),
        CheckConstraint("(owner_id IS NULL) = (lease_until IS NULL)"),
        CheckConstraint("(state IN ('preparing', 'ready', 'degraded', 'cancel_requested')) = (owner_id IS NOT NULL)"),
    )
    generation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    epoch: Mapped[int]
    state: Mapped[str]
    owner_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    lease_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class CodeIndexWorkerAttemptRecord(Base):
    __tablename__ = "code_index_worker_attempts"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "generation_id"],
            ["code_index_generations.project_id", "code_index_generations.generation_id"]),
        CheckConstraint("epoch > 0"),
    )
    generation_id: Mapped[str] = mapped_column(primary_key=True)
    epoch: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    owner_id: Mapped[str]
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CodeIndexProjectionRecord(Base):
    __tablename__ = "code_index_projection_pins"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "generation_id"],
            ["code_index_generations.project_id", "code_index_generations.generation_id"]),
        CheckConstraint("entity_count >= 0 AND relationship_count >= 0"),
    )
    generation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    projection_hash: Mapped[str]
    provider_version: Mapped[str]
    entity_count: Mapped[int]
    relationship_count: Mapped[int]


class CodeIndexProtocolRecord(Base):
    __tablename__ = "code_index_protocol_pins"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "generation_id"],
            ["code_index_generations.project_id", "code_index_generations.generation_id"]),
    )
    generation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    content_hash: Mapped[str]
    receipt: Mapped[dict] = mapped_column(JSONB)
