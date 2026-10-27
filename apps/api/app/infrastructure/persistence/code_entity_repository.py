from __future__ import annotations

from dataclasses import asdict
from typing import Sequence
from uuid import uuid4

from sqlalchemy import select, text

from ...application.platform.tool_models import EventPayload
from ...application.system_image.code_entity_registry import CodeEntityObservation, RegisteredCodeEntity
from ...application.system_image.system_image_models import RawAssetRecord
from ...domain.system_image.source_snapshots import snapshot_digest
from .code_entity_models import CodeEntityIdentityRecord, CodeEntityRevisionRecord, CodeEntityProviderBindingRecord
from .event_outbox_repository import EventOutboxRepository
from .source_snapshot_models import SourceBindingRecord, SourceRevisionRecord
from .source_evidence_repository import SourceEvidenceRepository
from .code_alias_projection_v1 import CodeAliasProjectorV1
from .unit_of_work import session_scope


class CodeEntityRepository:
    """Provider-neutral identities and audited aliases committed together."""

    def register(
        self, source: RawAssetRecord, observations: Sequence[CodeEntityObservation], *,
        provider: str, provider_version: str, captured_at: str,
    ) -> dict[str, RegisteredCodeEntity]:
        if source.source_type != "code":
            raise ValueError("code identity registry requires a code binding")
        with session_scope() as session:
            if session.get_bind().dialect.name == "postgresql":
                session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {
                    "key": f"nasus:code-entities:{source.project_id}",
                })
            binding = session.scalar(select(SourceBindingRecord).where(
                SourceBindingRecord.project_id == source.project_id,
                SourceBindingRecord.legacy_source_id == source.id,
                SourceBindingRecord.external_identity == source.source_uri,
                SourceBindingRecord.kind == "code",
            ))
            revision = session.scalar(select(SourceRevisionRecord).where(
                SourceRevisionRecord.project_id == source.project_id,
                SourceRevisionRecord.binding_id == binding.binding_id,
                SourceRevisionRecord.manifest_ref == source.content_ref,
                SourceRevisionRecord.content_hash == source.content_hash,
            )) if binding else None
            if revision is None:
                # Do not invent verified revisions for unarchived V1/demo sources.
                return {}
            keys = [item.symbol_key.fingerprint for item in observations]
            if len(set(keys)) != len(keys) or len({item.provider_node_id for item in observations}) != len(observations):
                raise ValueError("ambiguous code identity batch")
            extraction_digest = snapshot_digest([
                provider, provider_version,
                sorted((item.provider_node_id, item.symbol_key.fingerprint, snapshot_digest(item.payload)) for item in observations),
            ])
            registered: dict[str, RegisteredCodeEntity] = {}
            appended: list[str] = []
            alias_count = 0
            for item in observations:
                identity = session.scalar(select(CodeEntityIdentityRecord).where(
                    CodeEntityIdentityRecord.project_id == source.project_id,
                    CodeEntityIdentityRecord.binding_id == binding.binding_id,
                    CodeEntityIdentityRecord.symbol_key_hash == item.symbol_key.fingerprint,
                ))
                if identity is None:
                    identity = CodeEntityIdentityRecord(
                        entity_id=str(uuid4()), project_id=source.project_id, binding_id=binding.binding_id,
                        kind=item.symbol_key.kind, symbol_key_hash=item.symbol_key.fingerprint,
                        symbol_key=asdict(item.symbol_key), created_at=captured_at,
                    )
                    session.add(identity)
                    session.flush()
                elif snapshot_digest(identity.symbol_key) != item.symbol_key.fingerprint:
                    raise ValueError("code identity digest collision")
                payload_hash = snapshot_digest(item.payload)
                entity_revision = session.scalar(select(CodeEntityRevisionRecord).where(
                    CodeEntityRevisionRecord.entity_id == identity.entity_id,
                    CodeEntityRevisionRecord.source_revision_id == revision.source_revision_id,
                    CodeEntityRevisionRecord.payload_hash == payload_hash,
                ))
                if entity_revision is None:
                    entity_revision = CodeEntityRevisionRecord(
                        entity_revision_id=str(uuid4()), project_id=source.project_id,
                        binding_id=binding.binding_id, entity_id=identity.entity_id,
                        source_revision_id=revision.source_revision_id,
                        payload_hash=payload_hash, payload=item.payload, captured_at=captured_at,
                    )
                    session.add(entity_revision)
                    session.flush()
                    appended.append(entity_revision.entity_revision_id)
                SourceEvidenceRepository.append_for_entity(session, revision, entity_revision)
                mapping_key = dict(
                    project_id=source.project_id, binding_id=binding.binding_id,
                    source_revision_id=revision.source_revision_id, extraction_digest=extraction_digest,
                    provider_node_hash=snapshot_digest(item.provider_node_id),
                )
                mapping = session.get(CodeEntityProviderBindingRecord, mapping_key)
                if mapping is None:
                    mapping = CodeEntityProviderBindingRecord(
                        **mapping_key, provider=provider, provider_version=provider_version,
                        provider_node_id=item.provider_node_id, legacy_object_id=item.legacy_object_id,
                        entity_revision_id=entity_revision.entity_revision_id,
                    )
                    session.add(mapping)
                    session.flush()
                elif mapping.provider_node_id != item.provider_node_id or mapping.entity_revision_id != entity_revision.entity_revision_id:
                    raise ValueError("provider mapping digest collision")
                alias_count += CodeAliasProjectorV1.append(session, mapping, entity_revision, identity, binding)
                registered[item.provider_node_id] = RegisteredCodeEntity(
                    identity.entity_id, entity_revision.entity_revision_id, revision.source_revision_id,
                )
            if appended:
                EventOutboxRepository().append(EventPayload(
                    event_id=str(uuid4()), event_type="system_image.code_entities.registered",
                    occurred_at=captured_at, correlation_id=source.project_id,
                    entity_type="source_revision", entity_id=revision.source_revision_id,
                    entity_version=0, mutation_kind="append",
                    patch={"project_id": source.project_id, "binding_id": binding.binding_id,
                           "entity_revision_ids": appended, "mode": "canonical"},
                    query_keys=[["system-image", source.project_id]],
                ), session=session)
            if alias_count:
                EventOutboxRepository().append(EventPayload(
                    event_id=str(uuid4()), event_type="system_image.code_aliases.registered",
                    occurred_at=captured_at, correlation_id=source.project_id,
                    entity_type="source_revision", entity_id=revision.source_revision_id,
                    entity_version=0, mutation_kind="append",
                    patch={"project_id": source.project_id, "binding_id": binding.binding_id,
                           "source_revision_id": revision.source_revision_id, "alias_count": alias_count,
                           "extraction_digest": extraction_digest},
                    query_keys=[["system-image", source.project_id]],
                ), session=session)
            return registered
