from __future__ import annotations

from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class SourceBindingRecord(Base):
    __tablename__ = "source_bindings"
    __table_args__ = (
        UniqueConstraint("project_id", "binding_id"),
        UniqueConstraint("project_id", "legacy_source_id"),
        UniqueConstraint("project_id", "identity_hash"),
        CheckConstraint("kind IN ('code', 'us_doc', 'test_asset')"),
    )

    binding_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    legacy_source_id: Mapped[str]
    kind: Mapped[str]
    external_identity: Mapped[str]
    tracked_ref: Mapped[Optional[str]] = mapped_column(nullable=True)
    identity_hash: Mapped[str]
    registered_at: Mapped[str]


class SourceRevisionRecord(Base):
    __tablename__ = "source_revisions"
    __table_args__ = (
        UniqueConstraint("project_id", "binding_id", "source_revision_id"),
        UniqueConstraint("binding_id", "external_revision", "manifest_hash"),
        ForeignKeyConstraint(
            ["project_id", "binding_id"], ["source_bindings.project_id", "source_bindings.binding_id"],
        ),
        CheckConstraint("file_count > 0 AND byte_count >= 0"),
    )

    source_revision_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    binding_id: Mapped[str] = mapped_column(index=True)
    external_revision: Mapped[str]
    content_hash: Mapped[str]
    manifest_hash: Mapped[str]
    manifest_ref: Mapped[str]
    policy_version: Mapped[str]
    file_count: Mapped[int]
    byte_count: Mapped[int]
    acquired_at: Mapped[str]


class SourceManifestRecord(Base):
    __tablename__ = "source_manifests"
    __table_args__ = (
        UniqueConstraint("project_id", "manifest_id"),
        UniqueConstraint("project_id", "content_hash"),
    )

    manifest_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    content_hash: Mapped[str]
    captured_at: Mapped[str] = mapped_column(index=True)


class SourceManifestMemberRecord(Base):
    __tablename__ = "source_manifest_members"
    __table_args__ = (
        UniqueConstraint("project_id", "manifest_id", "binding_id", "source_revision_id", name="uq_manifest_source_pin"),
        ForeignKeyConstraint(
            ["project_id", "manifest_id"], ["source_manifests.project_id", "source_manifests.manifest_id"],
        ),
        ForeignKeyConstraint(
            ["project_id", "binding_id"], ["source_bindings.project_id", "source_bindings.binding_id"],
        ),
        ForeignKeyConstraint(
            ["project_id", "binding_id", "source_revision_id"],
            ["source_revisions.project_id", "source_revisions.binding_id", "source_revisions.source_revision_id"],
        ),
        CheckConstraint("status IN ('captured', 'failed', 'pending', 'legacy_unverified')"),
        CheckConstraint("(status = 'captured') = (source_revision_id IS NOT NULL)"),
    )

    manifest_id: Mapped[str] = mapped_column(primary_key=True)
    binding_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    source_type: Mapped[str]
    source_revision_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    status: Mapped[str]


class SourceManifestHeadRecord(Base):
    __tablename__ = "source_manifest_heads"
    __table_args__ = (ForeignKeyConstraint(
        ["project_id", "manifest_id"], ["source_manifests.project_id", "source_manifests.manifest_id"],
    ),)

    project_id: Mapped[str] = mapped_column(primary_key=True)
    manifest_id: Mapped[str]
