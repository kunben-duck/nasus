from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class ObjectProvenanceNodeRecord(Base):
    __tablename__ = "image_object_provenance_nodes"
    __table_args__ = (
        UniqueConstraint("project_id", "node_key", "content_hash", name="uq_object_provenance_node_pin"),
        CheckConstraint("kind IN ('source', 'manifest', 'code', 'document', 'evidence', 'member', 'image_objects')"),
        CheckConstraint("node_key = kind || ':' || artifact_id"),
        CheckConstraint("policy_revision = 'nasus.image-object-provenance.v1'"),
        Index("ix_object_provenance_kind", "project_id", "kind", "artifact_id"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    node_key: Mapped[str] = mapped_column(primary_key=True)
    kind: Mapped[str]
    artifact_id: Mapped[str]
    artifact_hash: Mapped[str]
    metadata_hash: Mapped[str]
    source_pins: Mapped[list] = mapped_column(JSON)
    content_hash: Mapped[str]
    policy_revision: Mapped[str]


class ObjectProvenanceEdgeRecord(Base):
    __tablename__ = "image_object_provenance_edges"
    __table_args__ = (
        *[ForeignKeyConstraint(["project_id", key, digest],
            ["image_object_provenance_nodes.project_id", "image_object_provenance_nodes.node_key",
             "image_object_provenance_nodes.content_hash"])
          for key, digest in (("node_key", "node_hash"), ("parent_key", "parent_hash"))],
        CheckConstraint("node_key <> parent_key"),
        Index("ix_object_provenance_reverse", "project_id", "parent_key", "node_key"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    node_key: Mapped[str] = mapped_column(primary_key=True)
    parent_key: Mapped[str] = mapped_column(primary_key=True)
    node_hash: Mapped[str]
    parent_hash: Mapped[str]


class ImageObjectProvenanceRecord(Base):
    __tablename__ = "image_object_provenance_roots"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "image_revision_id"],
            ["image_revisions.project_id", "image_revisions.image_revision_id"]),
        ForeignKeyConstraint(["project_id", "node_key", "content_hash"],
            ["image_object_provenance_nodes.project_id", "image_object_provenance_nodes.node_key",
             "image_object_provenance_nodes.content_hash"]),
        CheckConstraint("node_key = 'image_objects:' || image_revision_id"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    image_revision_id: Mapped[str] = mapped_column(primary_key=True)
    node_key: Mapped[str]
    content_hash: Mapped[str]
