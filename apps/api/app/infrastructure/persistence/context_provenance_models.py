from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class ContextProvenanceAnchorRecord(Base):
    __tablename__ = "system_image_context_provenance_anchors"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "context_id", "context_node_key", "context_registration_hash"],
            ["system_image_derivations.project_id", "system_image_derivations.context_id",
             "system_image_derivations.node_key", "system_image_derivations.content_hash"]),
        ForeignKeyConstraint(["project_id", "image_node_key", "image_provenance_hash"],
            ["image_object_provenance_nodes.project_id", "image_object_provenance_nodes.node_key",
             "image_object_provenance_nodes.content_hash"]),
        ForeignKeyConstraint(["project_id", "image_revision_id"],
            ["image_object_provenance_roots.project_id", "image_object_provenance_roots.image_revision_id"]),
        ForeignKeyConstraint(["project_id", "context_id", "manifest_id"],
            ["system_image_context_query_scopes.project_id", "system_image_context_query_scopes.context_id",
             "system_image_context_query_scopes.manifest_id"]),
        CheckConstraint("context_node_key = 'context:' || context_id"),
        CheckConstraint("image_node_key = 'image_objects:' || image_revision_id"),
        CheckConstraint("policy_revision = 'nasus.context-provenance-anchor.v1'"),
        Index("ix_context_provenance_image", "project_id", "image_revision_id", "context_id"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    context_id: Mapped[str] = mapped_column(primary_key=True)
    context_node_key: Mapped[str]
    context_registration_hash: Mapped[str]
    image_revision_id: Mapped[str]
    image_node_key: Mapped[str]
    image_artifact_hash: Mapped[str]
    image_provenance_hash: Mapped[str]
    manifest_id: Mapped[str]
    manifest_hash: Mapped[str]
    input_digest: Mapped[str]
    query_scope_fingerprint: Mapped[str]
    content_hash: Mapped[str]
    policy_revision: Mapped[str]
