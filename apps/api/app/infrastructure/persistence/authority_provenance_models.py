from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class AuthorityProvenanceRecord(Base):
    __tablename__ = "requirement_authority_provenance"
    __table_args__ = (
        UniqueConstraint("project_id", "kind", "revision_id", "content_hash", name="uq_authority_provenance_pin"),
        ForeignKeyConstraint(["project_id", "authority_id", "acceptance_revision_id"],
            ["quality_acceptance_revisions.project_id", "quality_acceptance_revisions.ac_id", "quality_acceptance_revisions.revision_id"]),
        ForeignKeyConstraint(["project_id", "authority_id", "business_rule_revision_id"],
            ["quality_business_rule_revisions.project_id", "quality_business_rule_revisions.rule_id", "quality_business_rule_revisions.revision_id"]),
        ForeignKeyConstraint(["project_id", "kind", "previous_revision_id", "previous_registration_hash"],
            ["requirement_authority_provenance.project_id", "requirement_authority_provenance.kind",
             "requirement_authority_provenance.revision_id", "requirement_authority_provenance.content_hash"]),
        *[ForeignKeyConstraint(["project_id", key, digest],
            ["image_object_provenance_nodes.project_id", "image_object_provenance_nodes.node_key",
             "image_object_provenance_nodes.content_hash"])
          for key, digest in (("image_node_key", "image_provenance_hash"),
                             ("member_node_key", "member_provenance_hash"),
                             ("document_node_key", "document_provenance_hash"))],
        CheckConstraint("(kind = 'acceptance' AND acceptance_revision_id = revision_id AND acceptance_revision_id IS NOT NULL AND business_rule_revision_id IS NULL) OR (kind = 'business_rule' AND business_rule_revision_id = revision_id AND business_rule_revision_id IS NOT NULL AND acceptance_revision_id IS NULL)"),
        CheckConstraint("status IN ('approved', 'withdrawn') AND sequence BETWEEN 1 AND 1000"),
        CheckConstraint("(sequence = 1 AND status = 'approved' AND previous_revision_id IS NULL AND previous_registration_hash IS NULL) OR (sequence > 1 AND previous_revision_id IS NOT NULL AND previous_registration_hash IS NOT NULL AND previous_revision_id <> revision_id)"),
        CheckConstraint("image_node_key = 'image_objects:' || image_revision_id"),
        CheckConstraint("member_node_key = 'member:' || image_revision_id || '/' || object_id"),
        CheckConstraint("document_node_key = 'document:' || document_revision_id"),
        CheckConstraint("policy_revision = 'nasus.requirement-authority-provenance.v1'"),
        Index("ix_authority_provenance_source", "project_id", "binding_id", "source_revision_id", "kind", "revision_id"),
        Index("ix_authority_provenance_member", "project_id", "image_revision_id", "object_id", "kind", "sequence"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(primary_key=True)
    revision_id: Mapped[str] = mapped_column(primary_key=True)
    authority_id: Mapped[str]
    metadata_hash: Mapped[str]
    artifact_hash: Mapped[str]
    image_revision_id: Mapped[str]
    image_artifact_hash: Mapped[str]
    object_id: Mapped[str]
    binding_id: Mapped[str]
    source_revision_id: Mapped[str]
    document_revision_id: Mapped[str]
    basis_digest: Mapped[str]
    invocation_id: Mapped[str]
    status: Mapped[str]
    sequence: Mapped[int]
    image_node_key: Mapped[str]
    image_provenance_hash: Mapped[str]
    member_node_key: Mapped[str]
    member_provenance_hash: Mapped[str]
    document_node_key: Mapped[str]
    document_provenance_hash: Mapped[str]
    previous_revision_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    previous_registration_hash: Mapped[Optional[str]] = mapped_column(nullable=True)
    acceptance_revision_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    business_rule_revision_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    content_hash: Mapped[str]
    policy_revision: Mapped[str]
