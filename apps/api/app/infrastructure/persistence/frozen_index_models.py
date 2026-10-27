from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, ForeignKey, ForeignKeyConstraint, UniqueConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class FrozenIndexReservationRecord(Base):
    __tablename__ = "image_index_reservations"
    __table_args__ = (
        UniqueConstraint("project_id", "invocation_id"),
        ForeignKeyConstraint(["project_id", "baseline_id", "publication_id"],
            ["image_publications.project_id", "image_publications.baseline_id", "image_publications.publication_id"]),
    )
    invocation_id: Mapped[str] = mapped_column(ForeignKey("tool_invocations.id"), primary_key=True)
    project_id: Mapped[str]
    baseline_id: Mapped[str]
    publication_id: Mapped[str]
    image_revision_id: Mapped[str]
    input_digest: Mapped[str]
    model_config_digest: Mapped[str]
    content_hash: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)


class FrozenIndexGenerationRecord(Base):
    __tablename__ = "image_index_generations"
    __table_args__ = (UniqueConstraint("project_id", "generation_id"),
        ForeignKeyConstraint(["project_id", "generation_id"],
            ["image_index_reservations.project_id", "image_index_reservations.invocation_id"]),)
    generation_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    publication_id: Mapped[str] = mapped_column(index=True)
    dimensions: Mapped[int]
    document_count: Mapped[int]
    artifact_ref: Mapped[str]
    artifact_hash: Mapped[str]
    created_at: Mapped[str]


class FrozenIndexDocumentRecord(Base):
    __tablename__ = "image_index_documents"
    __table_args__ = (ForeignKeyConstraint(["project_id", "generation_id"],
        ["image_index_generations.project_id", "image_index_generations.generation_id"]),)
    generation_id: Mapped[str] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    object_id: Mapped[str]
    source_revision_id: Mapped[str]
    binding_id: Mapped[str]
    text: Mapped[str] = mapped_column(Text)
    document_hash: Mapped[str]
    vector_hash: Mapped[str]
    embedding: Mapped[list] = mapped_column(Vector())


class FrozenRetrievalRecord(Base):
    __tablename__ = "image_retrieval_runs"
    __table_args__ = (UniqueConstraint("project_id", "retrieval_id", name="uq_frozen_retrieval_project_pin"),
        ForeignKeyConstraint(["project_id", "generation_id"],
        ["image_index_generations.project_id", "image_index_generations.generation_id"]),)
    retrieval_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    generation_id: Mapped[str]
    publication_id: Mapped[str]
    actor_id: Mapped[str]
    scope_fingerprint: Mapped[str]
    query_hash: Mapped[str]
    artifact_ref: Mapped[str]
    artifact_hash: Mapped[str]
    created_at: Mapped[str]
