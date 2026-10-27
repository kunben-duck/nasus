from __future__ import annotations

from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class SourceEvidenceRecord(Base):
    __tablename__ = "source_evidence"
    __table_args__ = (
        UniqueConstraint("project_id", "binding_id", "source_revision_id", "evidence_id"),
        UniqueConstraint("project_id", "binding_id", "source_revision_id", "identity_hash"),
        ForeignKeyConstraint(
            ["project_id", "binding_id", "source_revision_id"],
            ["source_revisions.project_id", "source_revisions.binding_id", "source_revisions.source_revision_id"],
        ),
        CheckConstraint("start_line >= 1 AND end_line >= start_line"),
        CheckConstraint("precision IN ('exact', 'approximate')"),
        CheckConstraint("(precision = 'exact') = (snippet_hash IS NOT NULL)"),
    )
    evidence_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    binding_id: Mapped[str]
    source_revision_id: Mapped[str]
    identity_hash: Mapped[str]
    relative_path: Mapped[str]
    start_line: Mapped[int]
    end_line: Mapped[int]
    precision: Mapped[str]
    file_hash: Mapped[str]
    snippet_hash: Mapped[Optional[str]] = mapped_column(nullable=True)
    object_ref: Mapped[str]
    decoder_version: Mapped[str]
    extractor_version: Mapped[str]
    captured_at: Mapped[str]


class CodeEntityEvidenceRecord(Base):
    __tablename__ = "code_entity_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "binding_id", "source_revision_id", "entity_revision_id"],
            ["code_entity_revisions.project_id", "code_entity_revisions.binding_id",
             "code_entity_revisions.source_revision_id", "code_entity_revisions.entity_revision_id"],
        ),
        ForeignKeyConstraint(
            ["project_id", "binding_id", "source_revision_id", "evidence_id"],
            ["source_evidence.project_id", "source_evidence.binding_id", "source_evidence.source_revision_id", "source_evidence.evidence_id"],
        ),
    )
    entity_revision_id: Mapped[str] = mapped_column(primary_key=True)
    evidence_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    binding_id: Mapped[str]
    source_revision_id: Mapped[str]
