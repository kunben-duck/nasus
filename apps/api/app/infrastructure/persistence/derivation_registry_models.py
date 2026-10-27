from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class DerivationRegistryRecord(Base):
    __tablename__ = "system_image_derivations"
    __table_args__ = (
        UniqueConstraint("project_id", "context_id", "node_key", name="uq_derivation_context_node"),
        UniqueConstraint("project_id", "context_id", "node_key", "content_hash", name="uq_derivation_registration_pin"),
        ForeignKeyConstraint(["project_id", "context_id"],
            ["system_image_context_packs.project_id", "system_image_context_packs.context_id"]),
        ForeignKeyConstraint(["invocation_id"], ["tool_invocations.id"]),
        CheckConstraint("kind IN ('context', 'scope', 'generation', 'case', 'coverage', 'mapping')"),
        CheckConstraint("node_key = kind || ':' || artifact_id"),
        Index("ix_derivation_context_kind", "project_id", "context_id", "kind", "artifact_id"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    node_key: Mapped[str] = mapped_column(primary_key=True)
    context_id: Mapped[str]
    kind: Mapped[str]
    artifact_id: Mapped[str]
    artifact_hash: Mapped[str]
    invocation_id: Mapped[str]
    policy_revision: Mapped[str]
    content_hash: Mapped[str]


class DerivationRegistryEdgeRecord(Base):
    __tablename__ = "system_image_derivation_edges"
    __table_args__ = (
        *[ForeignKeyConstraint(["project_id", "context_id", key],
            ["system_image_derivations.project_id", "system_image_derivations.context_id", "system_image_derivations.node_key"])
            for key in ("node_key", "parent_key")],
        CheckConstraint("node_key <> parent_key"),
        Index("ix_derivation_reverse_parent", "project_id", "parent_key", "node_key"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    node_key: Mapped[str] = mapped_column(primary_key=True)
    parent_key: Mapped[str] = mapped_column(primary_key=True)
    context_id: Mapped[str]


class ContextQueryScopeRecord(Base):
    __tablename__ = "system_image_context_query_scopes"
    __table_args__ = (
        UniqueConstraint("project_id", "context_id", "manifest_id", name="uq_query_scope_manifest_pin"),
        ForeignKeyConstraint(["project_id", "context_id"],
            ["system_image_context_packs.project_id", "system_image_context_packs.context_id"]),
        ForeignKeyConstraint(["project_id", "image_revision_id", "manifest_id"],
            ["image_revisions.project_id", "image_revisions.image_revision_id", "image_revisions.manifest_id"]),
        CheckConstraint("member_count > 0"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    context_id: Mapped[str] = mapped_column(primary_key=True)
    image_revision_id: Mapped[str]
    image_artifact_hash: Mapped[str]
    manifest_id: Mapped[str]
    manifest_hash: Mapped[str]
    input_digest: Mapped[str]
    query_scope_fingerprint: Mapped[str]
    source_members_hash: Mapped[str]
    member_count: Mapped[int]
    policy_revision: Mapped[str]


class ContextQuerySourceRecord(Base):
    __tablename__ = "system_image_context_query_sources"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "context_id", "manifest_id"],
            ["system_image_context_query_scopes.project_id", "system_image_context_query_scopes.context_id", "system_image_context_query_scopes.manifest_id"]),
        ForeignKeyConstraint(["manifest_id", "binding_id"],
            ["source_manifest_members.manifest_id", "source_manifest_members.binding_id"]),
        ForeignKeyConstraint(["project_id", "binding_id", "source_revision_id"],
            ["source_revisions.project_id", "source_revisions.binding_id", "source_revisions.source_revision_id"]),
        CheckConstraint("status IN ('captured', 'failed', 'pending', 'legacy_unverified')"),
        CheckConstraint("(status = 'captured') = (source_revision_id IS NOT NULL)"),
        Index("ix_query_source_reverse_revision", "project_id", "binding_id", "source_revision_id", "context_id"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    context_id: Mapped[str] = mapped_column(primary_key=True)
    binding_id: Mapped[str] = mapped_column(primary_key=True)
    manifest_id: Mapped[str]
    source_type: Mapped[str]
    source_revision_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    status: Mapped[str]
