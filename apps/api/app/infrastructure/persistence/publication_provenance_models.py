from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class PublicationProvenanceRecord(Base):
    __tablename__ = "image_publication_provenance"
    __table_args__ = (
        UniqueConstraint("project_id", "baseline_id", "kind", "fact_id", "content_hash", name="uq_publication_provenance_pin"),
        ForeignKeyConstraint(["project_id", "review_id"], ["image_publication_reviews.project_id", "image_publication_reviews.review_id"]),
        ForeignKeyConstraint(["project_id", "baseline_id", "publication_id"],
            ["image_publications.project_id", "image_publications.baseline_id", "image_publications.publication_id"]),
        ForeignKeyConstraint(["project_id", "manifest_id"], ["source_manifests.project_id", "source_manifests.manifest_id"]),
        *[ForeignKeyConstraint(["project_id", key, digest], [table + ".project_id", table + ".node_key", table + ".content_hash"])
          for key, digest, table in (("image_node_key", "image_provenance_hash", "image_object_provenance_nodes"),
              ("relations_node_key", "relations_provenance_hash", "image_relation_provenance_nodes"))],
        CheckConstraint("(kind = 'review' AND review_id IS NOT NULL AND review_id = fact_id AND publication_id IS NULL) OR (kind = 'publication' AND publication_id IS NOT NULL AND publication_id = fact_id AND review_id IS NULL)"),
        CheckConstraint("sequence > 0 AND dependency_count BETWEEN 0 AND 3"),
        CheckConstraint("image_node_key = 'image_objects:' || image_revision_id AND relations_node_key = 'image_relations:' || image_revision_id"),
        CheckConstraint("policy_revision = 'nasus.publication-provenance.v1'"),
        Index("ix_publication_provenance_image", "project_id", "image_revision_id", "baseline_id", "kind"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(primary_key=True)
    fact_id: Mapped[str] = mapped_column(primary_key=True)
    baseline_id: Mapped[str]
    image_revision_id: Mapped[str]
    image_artifact_hash: Mapped[str]
    manifest_id: Mapped[str]
    manifest_hash: Mapped[str]
    sequence: Mapped[int]
    metadata_hash: Mapped[str]
    request_hash: Mapped[str]
    invocation_id: Mapped[str]
    image_provenance_hash: Mapped[str]
    relations_provenance_hash: Mapped[str]
    image_node_key: Mapped[str]
    relations_node_key: Mapped[str]
    dependencies_hash: Mapped[str]
    dependency_count: Mapped[int]
    review_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    publication_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    policy_revision: Mapped[str]
    content_hash: Mapped[str]


class PublicationProvenanceDependencyRecord(Base):
    __tablename__ = "image_publication_dependencies"
    __table_args__ = (
        *[ForeignKeyConstraint(["project_id", "baseline_id", prefix + "kind", prefix + "id", prefix + "hash"],
            ["image_publication_provenance." + key for key in ("project_id", "baseline_id", "kind", "fact_id", "content_hash")])
          for prefix in ("fact_", "parent_")],
        CheckConstraint("(relation = 'previous_review' AND fact_kind = 'review' AND parent_kind = 'review') OR (relation = 'expected_head' AND fact_kind = 'review' AND parent_kind = 'publication') OR (relation = 'approval' AND fact_kind = 'publication' AND parent_kind = 'review') OR (relation IN ('previous_publication', 'rollback_source') AND parent_kind = 'publication' AND (relation = 'rollback_source' OR fact_kind = 'publication'))"),
        CheckConstraint("fact_kind <> parent_kind OR fact_id <> parent_id"),
        Index("ix_publication_dependency_parent", "project_id", "parent_kind", "parent_id"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    fact_kind: Mapped[str] = mapped_column(primary_key=True)
    fact_id: Mapped[str] = mapped_column(primary_key=True)
    relation: Mapped[str] = mapped_column(primary_key=True)
    baseline_id: Mapped[str]
    fact_hash: Mapped[str]
    parent_kind: Mapped[str]
    parent_id: Mapped[str]
    parent_hash: Mapped[str]


class ContextPublicationDependencyRecord(Base):
    __tablename__ = "context_publication_dependencies"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "context_id"], ["system_image_context_packs.project_id", "system_image_context_packs.context_id"]),
        ForeignKeyConstraint(["project_id", "baseline_id", "publication_kind", "publication_id", "publication_registration_hash"],
            ["image_publication_provenance." + key for key in ("project_id", "baseline_id", "kind", "fact_id", "content_hash")]),
        CheckConstraint("publication_kind = 'publication' AND policy_revision = 'nasus.publication-provenance.v1'"),
        Index("ix_context_publication_dependency", "project_id", "publication_id", "context_id"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    context_id: Mapped[str] = mapped_column(primary_key=True)
    context_metadata_hash: Mapped[str]
    context_request_hash: Mapped[str]
    image_revision_id: Mapped[str]
    image_artifact_hash: Mapped[str]
    baseline_id: Mapped[str]
    publication_kind: Mapped[str]
    publication_id: Mapped[str]
    publication_registration_hash: Mapped[str]
    policy_revision: Mapped[str]
    content_hash: Mapped[str]
