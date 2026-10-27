from __future__ import annotations

from typing import Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class ImageRevisionRecord(Base):
    __tablename__ = "image_revisions"
    __table_args__ = (
        UniqueConstraint("project_id", "image_revision_id"),
        UniqueConstraint("project_id", "image_revision_id", "manifest_id"),
        UniqueConstraint("project_id", "baseline_id", "manifest_id", "artifact_hash"),
        ForeignKeyConstraint(["project_id", "manifest_id"], ["source_manifests.project_id", "source_manifests.manifest_id"]),
        ForeignKeyConstraint(["project_id", "parent_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"], name="fk_image_review_parent"),
        CheckConstraint("status = 'candidate'"),
        CheckConstraint("(policy_version = 'nasus.image-candidate.v1' AND parent_revision_id IS NULL AND parent_artifact_hash IS NULL AND assertion_count = 0) OR (policy_version IN ('nasus.image-candidate.v2', 'nasus.image-candidate.v3') AND parent_revision_id IS NOT NULL AND parent_revision_id <> image_revision_id AND parent_artifact_hash IS NOT NULL AND assertion_count BETWEEN 1 AND 1000)", name="ck_image_review_membership"),
    )
    image_revision_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(index=True)
    baseline_id: Mapped[str]
    manifest_id: Mapped[str]
    manifest_hash: Mapped[str]
    artifact_ref: Mapped[str]
    artifact_hash: Mapped[str]
    membership_hash: Mapped[str]
    policy_version: Mapped[str]
    recorded_at: Mapped[str]
    status: Mapped[str]
    object_count: Mapped[int]
    code_member_count: Mapped[int]
    relationship_count: Mapped[int]
    parent_revision_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    parent_artifact_hash: Mapped[Optional[str]] = mapped_column(nullable=True)
    assertion_count: Mapped[int] = mapped_column(default=0, server_default="0")


class ImageAssertionMemberRecord(Base):
    __tablename__ = "image_assertion_members"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        ForeignKeyConstraint(["project_id", "origin_image_revision_id"], ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        ForeignKeyConstraint(["project_id", "proposal_id", "assertion_id"],
            ["image_reference_assertions.project_id", "image_reference_assertions.proposal_id", "image_reference_assertions.assertion_id"]),
        ForeignKeyConstraint(["project_id", "assertion_id", "decision_id"],
            ["image_link_decisions.project_id", "image_link_decisions.assertion_id", "image_link_decisions.decision_id"]),
    )
    image_revision_id: Mapped[str] = mapped_column(primary_key=True)
    assertion_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    proposal_id: Mapped[str]
    decision_id: Mapped[str]
    origin_image_revision_id: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class ImageObjectMemberRecord(Base):
    __tablename__ = "image_object_members"
    __table_args__ = (
        UniqueConstraint("image_revision_id", "object_id", "document_revision_id", name="uq_image_reference_endpoint"),
        ForeignKeyConstraint(["project_id", "image_revision_id", "manifest_id"],
            ["image_revisions.project_id", "image_revisions.image_revision_id", "image_revisions.manifest_id"]),
        ForeignKeyConstraint(["project_id", "manifest_id", "binding_id", "source_revision_id"],
            ["source_manifest_members.project_id", "source_manifest_members.manifest_id",
             "source_manifest_members.binding_id", "source_manifest_members.source_revision_id"]),
        ForeignKeyConstraint(["project_id", "binding_id", "entity_id", "source_revision_id", "entity_revision_id"],
            ["code_entity_revisions.project_id", "code_entity_revisions.binding_id", "code_entity_revisions.entity_id",
             "code_entity_revisions.source_revision_id", "code_entity_revisions.entity_revision_id"]),
        ForeignKeyConstraint(["project_id", "binding_id", "source_revision_id", "document_revision_id"],
            ["source_document_revisions.project_id", "source_document_revisions.binding_id",
             "source_document_revisions.source_revision_id", "source_document_revisions.document_revision_id"]),
        CheckConstraint("kind IN ('code_entity', 'source_document', 'legacy_observation')"),
        CheckConstraint("(kind = 'code_entity' AND binding_id IS NOT NULL AND entity_id IS NOT NULL AND entity_revision_id IS NOT NULL AND source_revision_id IS NOT NULL AND document_revision_id IS NULL) OR (kind = 'source_document' AND binding_id IS NOT NULL AND source_revision_id IS NOT NULL AND document_revision_id IS NOT NULL AND entity_id IS NULL AND entity_revision_id IS NULL) OR (kind = 'legacy_observation' AND binding_id IS NULL AND entity_id IS NULL AND entity_revision_id IS NULL AND source_revision_id IS NULL AND document_revision_id IS NULL)"),
    )
    image_revision_id: Mapped[str] = mapped_column(primary_key=True)
    object_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    manifest_id: Mapped[str]
    object_hash: Mapped[str]
    kind: Mapped[str]
    binding_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    entity_revision_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    source_revision_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    evidence_ids: Mapped[list] = mapped_column(JSON)
    document_revision_id: Mapped[Optional[str]] = mapped_column(nullable=True)


class ImageRevisionInvocationRecord(Base):
    __tablename__ = "image_revision_invocations"
    __table_args__ = (ForeignKeyConstraint(["project_id", "image_revision_id"],
        ["image_revisions.project_id", "image_revisions.image_revision_id"]),)
    project_id: Mapped[str] = mapped_column(primary_key=True)
    image_revision_id: Mapped[str] = mapped_column(primary_key=True)
    invocation_id: Mapped[str] = mapped_column(primary_key=True)
