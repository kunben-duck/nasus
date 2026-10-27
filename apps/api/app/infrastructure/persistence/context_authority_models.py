from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class ContextAuthorityRootRecord(Base):
    __tablename__ = "system_image_context_authority_roots"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "context_id"],
            ["system_image_context_packs.project_id", "system_image_context_packs.context_id"]),
        ForeignKeyConstraint(["registration_invocation_id"], ["tool_invocations.id"]),
        CheckConstraint("authority_count BETWEEN 0 AND 256"),
        CheckConstraint("policy_revision = 'nasus.context-authority-dependencies.v1'"),
        Index("ix_context_authority_roots_image", "project_id", "image_revision_id", "context_id"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    context_id: Mapped[str] = mapped_column(primary_key=True)
    image_revision_id: Mapped[str]
    image_artifact_hash: Mapped[str]
    input_digest: Mapped[str]
    artifact_hash: Mapped[str]
    invocation_id: Mapped[str]
    context_metadata_hash: Mapped[str]
    registration_invocation_id: Mapped[str]
    registered_by: Mapped[str]
    registered_at: Mapped[str]
    policy_revision: Mapped[str]
    authority_count: Mapped[int]
    authority_pins_hash: Mapped[str]
    content_hash: Mapped[str]


class ContextAuthorityDependencyRecord(Base):
    __tablename__ = "system_image_context_authority_dependencies"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "context_id"],
            ["system_image_context_authority_roots.project_id", "system_image_context_authority_roots.context_id"]),
        ForeignKeyConstraint(["project_id", "kind", "revision_id", "authority_registration_hash"],
            ["requirement_authority_provenance.project_id", "requirement_authority_provenance.kind",
             "requirement_authority_provenance.revision_id", "requirement_authority_provenance.content_hash"]),
        ForeignKeyConstraint(["project_id", "member_node_key", "member_provenance_hash"],
            ["image_object_provenance_nodes.project_id", "image_object_provenance_nodes.node_key",
             "image_object_provenance_nodes.content_hash"]),
        CheckConstraint("kind IN ('acceptance', 'business_rule')"),
        CheckConstraint("(status = 'unapproved' AND revision_id IS NULL AND artifact_hash IS NULL AND authority_registration_hash IS NULL) OR (status IN ('approved', 'withdrawn') AND revision_id IS NOT NULL AND artifact_hash IS NOT NULL AND authority_registration_hash IS NOT NULL)"),
        CheckConstraint("member_node_key = 'member:' || image_revision_id || '/' || object_id"),
        CheckConstraint("policy_revision = 'nasus.context-authority-dependencies.v1'"),
        Index("ix_context_authority_revision", "project_id", "kind", "revision_id", "context_id"),
        Index("ix_context_authority_member", "project_id", "image_revision_id", "object_id", "context_id"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    context_id: Mapped[str] = mapped_column(primary_key=True)
    object_id: Mapped[str] = mapped_column(primary_key=True)
    kind: Mapped[str]
    basis_digest: Mapped[str]
    status: Mapped[str]
    revision_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    artifact_hash: Mapped[Optional[str]] = mapped_column(nullable=True)
    authority_registration_hash: Mapped[Optional[str]] = mapped_column(nullable=True)
    image_revision_id: Mapped[str]
    member_provenance_hash: Mapped[str]
    member_node_key: Mapped[str]
    policy_revision: Mapped[str]
    content_hash: Mapped[str]


class ContextAuthorityBackfillTargetRecord(Base):
    """Migration-only inventory; missing dependencies on new contexts are corruption."""
    __tablename__ = "system_image_context_authority_backfill_targets"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "context_id"],
            ["system_image_context_packs.project_id", "system_image_context_packs.context_id"]),
        CheckConstraint("policy_revision = 'nasus.context-authority-dependencies.v1'"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    context_id: Mapped[str] = mapped_column(primary_key=True)
    context_metadata_hash: Mapped[str]
    artifact_hash: Mapped[str]
    policy_revision: Mapped[str]
