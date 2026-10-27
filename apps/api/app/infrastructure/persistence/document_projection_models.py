from __future__ import annotations

from typing import Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class SourceDocumentIdentityRecord(Base):
    __tablename__ = "source_document_identities"
    __table_args__ = (
        UniqueConstraint("project_id", "binding_id", "identity_hash"),
        UniqueConstraint("project_id", "binding_id", "entity_id"),
        ForeignKeyConstraint(["project_id", "binding_id"], ["source_bindings.project_id", "source_bindings.binding_id"]),
    )
    entity_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    binding_id: Mapped[str]
    identity_hash: Mapped[str]
    identity_key: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str]


class SourceDocumentRevisionRecord(Base):
    __tablename__ = "source_document_revisions"
    __table_args__ = (
        UniqueConstraint("entity_id", "source_revision_id", "payload_hash"),
        UniqueConstraint("project_id", "binding_id", "source_revision_id", "document_revision_id"),
        CheckConstraint("(kind IN ('acceptance_criterion', 'business_rule') AND parent_document_revision_id IS NOT NULL AND parent_document_revision_id <> document_revision_id) OR (kind NOT IN ('acceptance_criterion', 'business_rule') AND parent_document_revision_id IS NULL)", name="ck_source_document_parent"),
        ForeignKeyConstraint(["project_id", "binding_id", "source_revision_id", "parent_document_revision_id"],
            ["source_document_revisions.project_id", "source_document_revisions.binding_id",
             "source_document_revisions.source_revision_id", "source_document_revisions.document_revision_id"], name="fk_source_document_parent"),
        ForeignKeyConstraint(["project_id", "binding_id", "source_revision_id"],
            ["source_revisions.project_id", "source_revisions.binding_id", "source_revisions.source_revision_id"]),
        ForeignKeyConstraint(["project_id", "binding_id", "entity_id"],
            ["source_document_identities.project_id", "source_document_identities.binding_id", "source_document_identities.entity_id"]),
    )
    document_revision_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    binding_id: Mapped[str]
    source_revision_id: Mapped[str]
    entity_id: Mapped[str]
    title: Mapped[str]
    kind: Mapped[str]
    payload_ref: Mapped[str]
    payload_hash: Mapped[str]
    captured_at: Mapped[str]
    parent_document_revision_id: Mapped[Optional[str]] = mapped_column(nullable=True)


class SourceDocumentEvidenceRecord(Base):
    __tablename__ = "source_document_evidence"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "binding_id", "source_revision_id", "document_revision_id"],
            ["source_document_revisions.project_id", "source_document_revisions.binding_id",
             "source_document_revisions.source_revision_id", "source_document_revisions.document_revision_id"]),
        ForeignKeyConstraint(["project_id", "binding_id", "source_revision_id", "evidence_id"],
            ["source_evidence.project_id", "source_evidence.binding_id", "source_evidence.source_revision_id", "source_evidence.evidence_id"]),
    )
    document_revision_id: Mapped[str] = mapped_column(primary_key=True)
    evidence_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    binding_id: Mapped[str]
    source_revision_id: Mapped[str]


class SourceDocumentExtractionRecord(Base):
    __tablename__ = "source_document_extractions"
    __table_args__ = (
        UniqueConstraint("project_id", "source_revision_id", "report_hash"),
        ForeignKeyConstraint(["project_id", "binding_id", "source_revision_id"],
            ["source_revisions.project_id", "source_revisions.binding_id", "source_revisions.source_revision_id"]),
    )
    extraction_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    binding_id: Mapped[str]
    source_revision_id: Mapped[str]
    report_ref: Mapped[str]
    report_hash: Mapped[str]
    summary: Mapped[dict] = mapped_column(JSON)
    captured_at: Mapped[str]
