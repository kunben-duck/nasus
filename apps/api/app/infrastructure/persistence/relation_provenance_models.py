from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class RelationProvenanceNodeRecord(Base):
    __tablename__ = "image_relation_provenance_nodes"
    __table_args__ = (
        UniqueConstraint("project_id", "node_key", "content_hash", name="uq_relation_provenance_node_pin"),
        ForeignKeyConstraint(["project_id", "object_node_key", "object_node_hash"],
            ["image_object_provenance_nodes.project_id", "image_object_provenance_nodes.node_key",
             "image_object_provenance_nodes.content_hash"]),
        CheckConstraint("kind IN ('object_pin', 'reference_proposal', 'reference_assertion', 'reference_decision', "
            "'semantic_evaluation', 'semantic_assertion', 'semantic_decision', 'relation_member', 'image_relations')"),
        CheckConstraint("node_key = kind || ':' || artifact_id"),
        CheckConstraint("policy_revision = 'nasus.image-relation-provenance.v1'"),
        CheckConstraint("(kind = 'object_pin' AND object_node_key = artifact_id AND object_node_key IS NOT NULL "
            "AND object_node_hash IS NOT NULL AND object_node_hash = artifact_hash) OR "
            "(kind <> 'object_pin' AND object_node_key IS NULL AND object_node_hash IS NULL)"),
        Index("ix_relation_provenance_kind", "project_id", "kind", "artifact_id"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    node_key: Mapped[str] = mapped_column(primary_key=True)
    kind: Mapped[str]
    artifact_id: Mapped[str]
    artifact_hash: Mapped[str]
    metadata_hash: Mapped[str]
    object_node_key: Mapped[Optional[str]] = mapped_column(nullable=True)
    object_node_hash: Mapped[Optional[str]] = mapped_column(nullable=True)
    content_hash: Mapped[str]
    policy_revision: Mapped[str]


class RelationProvenanceEdgeRecord(Base):
    __tablename__ = "image_relation_provenance_edges"
    __table_args__ = (
        *[ForeignKeyConstraint(["project_id", key, digest],
            ["image_relation_provenance_nodes.project_id", "image_relation_provenance_nodes.node_key",
             "image_relation_provenance_nodes.content_hash"])
          for key, digest in (("node_key", "node_hash"), ("parent_key", "parent_hash"))],
        CheckConstraint("node_key <> parent_key"),
        Index("ix_relation_provenance_reverse", "project_id", "parent_key", "node_key"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    node_key: Mapped[str] = mapped_column(primary_key=True)
    parent_key: Mapped[str] = mapped_column(primary_key=True)
    node_hash: Mapped[str]
    parent_hash: Mapped[str]


class ImageRelationProvenanceRecord(Base):
    __tablename__ = "image_relation_provenance_roots"
    __table_args__ = (
        UniqueConstraint("project_id", "image_revision_id", "node_key", "content_hash", name="uq_image_relation_root_pin"),
        ForeignKeyConstraint(["project_id", "image_revision_id"],
            ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        ForeignKeyConstraint(["project_id", "node_key", "content_hash"],
            ["image_relation_provenance_nodes.project_id", "image_relation_provenance_nodes.node_key",
             "image_relation_provenance_nodes.content_hash"]),
        CheckConstraint("node_key = 'image_relations:' || image_revision_id"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    image_revision_id: Mapped[str] = mapped_column(primary_key=True)
    node_key: Mapped[str]
    content_hash: Mapped[str]


class ContextRelationProvenanceRecord(Base):
    __tablename__ = "system_image_context_relation_anchors"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "context_id"],
            ["system_image_context_provenance_anchors.project_id", "system_image_context_provenance_anchors.context_id"]),
        ForeignKeyConstraint(["project_id", "image_revision_id", "image_node_key", "image_relations_hash"],
            ["image_relation_provenance_roots.project_id", "image_relation_provenance_roots.image_revision_id",
             "image_relation_provenance_roots.node_key", "image_relation_provenance_roots.content_hash"]),
        CheckConstraint("image_node_key = 'image_relations:' || image_revision_id"),
        Index("ix_context_relation_image", "project_id", "image_revision_id", "context_id"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    context_id: Mapped[str] = mapped_column(primary_key=True)
    image_revision_id: Mapped[str]
    image_node_key: Mapped[str]
    image_relations_hash: Mapped[str]
    source_anchor_hash: Mapped[str]
    content_hash: Mapped[str]
