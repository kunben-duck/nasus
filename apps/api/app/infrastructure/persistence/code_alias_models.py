from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class CodeObjectAliasRecord(Base):
    __tablename__ = "code_object_aliases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "binding_id", "source_revision_id", "extraction_digest", "provider_node_hash", "entity_revision_id", "legacy_object_id"],
            ["code_entity_provider_bindings.project_id", "code_entity_provider_bindings.binding_id",
             "code_entity_provider_bindings.source_revision_id", "code_entity_provider_bindings.extraction_digest",
             "code_entity_provider_bindings.provider_node_hash", "code_entity_provider_bindings.entity_revision_id", "code_entity_provider_bindings.legacy_object_id"],
        ),
        ForeignKeyConstraint(
            ["project_id", "binding_id", "source_revision_id", "entity_revision_id", "entity_id"],
            ["code_entity_revisions.project_id", "code_entity_revisions.binding_id",
             "code_entity_revisions.source_revision_id", "code_entity_revisions.entity_revision_id", "code_entity_revisions.entity_id"],
        ),
        CheckConstraint("canonical_object_id = 'CODE-' || entity_id"),
        CheckConstraint("policy_version = 'nasus.code-object-alias.v1'"),
        Index("ix_code_alias_legacy_scope", "project_id", "source_revision_id", "legacy_object_id", "entity_revision_id"),
        Index("ix_code_alias_canonical_scope", "project_id", "source_revision_id", "canonical_object_id", "entity_revision_id"),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    binding_id: Mapped[str] = mapped_column(primary_key=True)
    source_revision_id: Mapped[str] = mapped_column(primary_key=True)
    extraction_digest: Mapped[str] = mapped_column(primary_key=True)
    provider_node_hash: Mapped[str] = mapped_column(primary_key=True)
    entity_id: Mapped[str]
    entity_revision_id: Mapped[str]
    legacy_object_id: Mapped[str]
    canonical_object_id: Mapped[str]
    policy_version: Mapped[str]
    content_hash: Mapped[str]
