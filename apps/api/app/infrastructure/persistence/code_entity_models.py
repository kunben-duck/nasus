from __future__ import annotations

from sqlalchemy import JSON, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class CodeEntityIdentityRecord(Base):
    __tablename__ = "code_entity_identities"
    __table_args__ = (
        UniqueConstraint("project_id", "binding_id", "entity_id"),
        UniqueConstraint("project_id", "binding_id", "symbol_key_hash"),
        ForeignKeyConstraint(["project_id", "binding_id"], ["source_bindings.project_id", "source_bindings.binding_id"]),
    )
    entity_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    binding_id: Mapped[str]
    kind: Mapped[str]
    symbol_key_hash: Mapped[str]
    symbol_key: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str]


class CodeEntityRevisionRecord(Base):
    __tablename__ = "code_entity_revisions"
    __table_args__ = (
        UniqueConstraint("project_id", "binding_id", "source_revision_id", "entity_revision_id"),
        UniqueConstraint("project_id", "binding_id", "entity_id", "source_revision_id", "entity_revision_id", name="uq_code_revision_complete_pin"),
        UniqueConstraint("entity_id", "source_revision_id", "payload_hash"),
        UniqueConstraint("project_id", "binding_id", "source_revision_id", "entity_revision_id", "entity_id", name="uq_code_alias_revision_pin"),
        ForeignKeyConstraint(
            ["project_id", "binding_id", "entity_id"],
            ["code_entity_identities.project_id", "code_entity_identities.binding_id", "code_entity_identities.entity_id"],
        ),
        ForeignKeyConstraint(
            ["project_id", "binding_id", "source_revision_id"],
            ["source_revisions.project_id", "source_revisions.binding_id", "source_revisions.source_revision_id"],
        ),
    )
    entity_revision_id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str]
    binding_id: Mapped[str]
    entity_id: Mapped[str]
    source_revision_id: Mapped[str]
    payload_hash: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    captured_at: Mapped[str]


class CodeEntityProviderBindingRecord(Base):
    __tablename__ = "code_entity_provider_bindings"
    __table_args__ = (
        UniqueConstraint("project_id", "binding_id", "source_revision_id", "extraction_digest", "provider_node_hash", "entity_revision_id", "legacy_object_id", name="uq_code_alias_mapping_pin"),
        ForeignKeyConstraint(
            ["project_id", "binding_id", "source_revision_id", "entity_revision_id"],
            ["code_entity_revisions.project_id", "code_entity_revisions.binding_id",
             "code_entity_revisions.source_revision_id", "code_entity_revisions.entity_revision_id"],
        ),
    )
    project_id: Mapped[str] = mapped_column(primary_key=True)
    binding_id: Mapped[str] = mapped_column(primary_key=True)
    source_revision_id: Mapped[str] = mapped_column(primary_key=True)
    extraction_digest: Mapped[str] = mapped_column(primary_key=True)
    provider_node_hash: Mapped[str] = mapped_column(primary_key=True)
    provider: Mapped[str]
    provider_version: Mapped[str]
    provider_node_id: Mapped[str]
    entity_revision_id: Mapped[str]
    legacy_object_id: Mapped[str] = mapped_column(index=True)
