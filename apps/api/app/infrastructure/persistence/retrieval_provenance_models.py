from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class RetrievalProvenanceRecord(Base):
    __tablename__ = "image_retrieval_provenance"
    __table_args__ = (
        UniqueConstraint("project_id", "kind", "artifact_id", "content_hash", name="uq_retrieval_provenance_pin"),
        ForeignKeyConstraint(["project_id", "reservation_id"], ["image_index_reservations.project_id", "image_index_reservations.invocation_id"]),
        ForeignKeyConstraint(["project_id", "generation_id"], ["image_index_generations.project_id", "image_index_generations.generation_id"]),
        ForeignKeyConstraint(["project_id", "retrieval_id"], ["image_retrieval_runs.project_id", "image_retrieval_runs.retrieval_id"]),
        ForeignKeyConstraint(["project_id", "baseline_id", "publication_kind", "publication_id", "publication_registration_hash"],
            ["image_publication_provenance." + key for key in ("project_id", "baseline_id", "kind", "fact_id", "content_hash")]),
        ForeignKeyConstraint(["project_id", "parent_kind", "parent_id", "parent_hash"],
            ["image_retrieval_provenance." + key for key in ("project_id", "kind", "artifact_id", "content_hash")]),
        CheckConstraint("(kind = 'reservation' AND reservation_id = artifact_id AND reservation_id IS NOT NULL AND generation_id IS NULL AND retrieval_id IS NULL AND parent_kind IS NULL AND parent_id IS NULL AND parent_hash IS NULL) OR (kind = 'generation' AND generation_id = artifact_id AND generation_id IS NOT NULL AND reservation_id IS NULL AND retrieval_id IS NULL AND parent_kind IS NOT NULL AND parent_kind = 'reservation' AND parent_id IS NOT NULL AND parent_hash IS NOT NULL) OR (kind = 'retrieval' AND retrieval_id = artifact_id AND retrieval_id IS NOT NULL AND reservation_id IS NULL AND generation_id IS NULL AND parent_kind IS NOT NULL AND parent_kind = 'generation' AND parent_id IS NOT NULL AND parent_hash IS NOT NULL)"),
        CheckConstraint("document_count BETWEEN 0 AND 4096 AND ((kind = 'generation') = (document_count > 0))"),
        CheckConstraint("publication_kind = 'publication' AND policy_revision = 'nasus.retrieval-provenance.v1'"),
        Index("ix_retrieval_provenance_parent", "project_id", "parent_kind", "parent_id"),
        Index("ix_retrieval_provenance_publication", "project_id", "publication_id", "kind"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(primary_key=True)
    artifact_id: Mapped[str] = mapped_column(primary_key=True)
    metadata_hash: Mapped[str]
    baseline_id: Mapped[str]
    publication_kind: Mapped[str]
    publication_id: Mapped[str]
    image_revision_id: Mapped[str]
    image_artifact_hash: Mapped[str]
    publication_registration_hash: Mapped[str]
    parent_kind: Mapped[Optional[str]] = mapped_column(nullable=True)
    parent_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    parent_hash: Mapped[Optional[str]] = mapped_column(nullable=True)
    documents_hash: Mapped[str]
    document_count: Mapped[int]
    reservation_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    generation_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    retrieval_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    policy_revision: Mapped[str]
    content_hash: Mapped[str]


class IndexDocumentDependencyRecord(Base):
    __tablename__ = "image_index_document_dependencies"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "generation_kind", "generation_id", "generation_hash"],
            ["image_retrieval_provenance." + key for key in ("project_id", "kind", "artifact_id", "content_hash")]),
        ForeignKeyConstraint(["generation_id", "document_id"], ["image_index_documents.generation_id", "image_index_documents.document_id"]),
        ForeignKeyConstraint(["project_id", "member_key", "member_hash"],
            ["image_object_provenance_nodes.project_id", "image_object_provenance_nodes.node_key", "image_object_provenance_nodes.content_hash"]),
        CheckConstraint("generation_kind = 'generation'"),
        Index("ix_index_document_dependency_member", "project_id", "member_key", "generation_id"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    generation_id: Mapped[str] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(primary_key=True)
    generation_kind: Mapped[str]
    generation_hash: Mapped[str]
    document_hash: Mapped[str]
    member_key: Mapped[str]
    member_hash: Mapped[str]


class ContextRetrievalDependencyRecord(Base):
    __tablename__ = "context_retrieval_dependencies"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "context_id"], ["system_image_context_packs.project_id", "system_image_context_packs.context_id"]),
        ForeignKeyConstraint(["image_revision_id", "target_object_id"], ["image_object_members.image_revision_id", "image_object_members.object_id"]),
        ForeignKeyConstraint(["project_id", "retrieval_kind", "retrieval_id", "retrieval_hash"],
            ["image_retrieval_provenance." + key for key in ("project_id", "kind", "artifact_id", "content_hash")]),
        CheckConstraint("retrieval_kind = 'retrieval'"),
        Index("ix_context_retrieval_dependency", "project_id", "retrieval_id", "context_id"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    context_id: Mapped[str] = mapped_column(primary_key=True)
    target_object_id: Mapped[str] = mapped_column(primary_key=True)
    image_revision_id: Mapped[str]
    context_metadata_hash: Mapped[str]
    context_request_hash: Mapped[str]
    retrieval_kind: Mapped[str]
    retrieval_id: Mapped[str]
    retrieval_hash: Mapped[str]
    content_hash: Mapped[str]
