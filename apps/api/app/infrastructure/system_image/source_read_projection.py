from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace

from sqlalchemy import and_, or_, select

from ...application.platform.errors import PlatformApplicationError
from ...application.system_image.retrieval_scope import AuthorizedRetrievalSubjects, RetrievalSubjectProvenance
from ...application.system_image.system_image_models import KnowledgeCodeReference, KnowledgeDocumentReference, KnowledgeObject
from ...domain.system_image.source_access import SourceAccessScope
from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from ...domain.system_image.source_snapshots import snapshot_digest
from ..persistence.code_alias_models import CodeObjectAliasRecord
from ..persistence.code_alias_repository import verified_code_alias
from ..persistence.code_entity_models import CodeEntityRevisionRecord
from ..persistence.document_projection_models import SourceDocumentRevisionRecord
from ..persistence.system_image_repository import SystemImageProjectSnapshot
from ..persistence.unit_of_work import session_scope


@dataclass(frozen=True)
class SourceReadProjection:
    snapshot: SystemImageProjectSnapshot
    index_subjects: AuthorizedRetrievalSubjects | None
    include_unproven_memory: bool


class SQLAlchemySourceReadProjection:
    """Read-only projection, never passed to replace_system_image or a workspace."""

    def project(self, snapshot: SystemImageProjectSnapshot, scope: SourceAccessScope) -> SourceReadProjection:
        if not scope.requires_provenance:
            # An inherited project-only policy preserves legacy V1 projections.
            # This branch still requires current membership and epoch rechecks.
            return SourceReadProjection(deepcopy(snapshot), None, True)
        sources = [item.model_copy(deep=True) for item in snapshot.raw_assets
                   if item.project_id == scope.project_id and item.id in scope.source_ids]
        source_ids = {item.id for item in sources}
        chunks = [item.model_copy(deep=True) for item in snapshot.raw_asset_chunks
                  if item.project_id == scope.project_id and item.raw_asset_id in source_ids]
        objects = self._code_objects(snapshot, scope) + self._document_objects(snapshot, scope)
        provenance = [RetrievalSubjectProvenance(scope.project_id, f"raw_asset:{item.id}", (item.id,), True)
                      for item in sources]
        provenance.extend(RetrievalSubjectProvenance(
            scope.project_id, f"raw_asset_chunk:{item.id}", (item.raw_asset_id,), True,
        ) for item in chunks)
        subjects = AuthorizedRetrievalSubjects.compile(scope, provenance)
        allowed_refs = set(subjects.subject_refs)
        embeddings = [item.model_copy(deep=True) for item in snapshot.embedding_records
                      if item.project_id == scope.project_id and self._subject_ref(item) in allowed_refs]
        # Unpinned object embeddings contain relation names from other sources.
        # They are excluded, rather than relying on a post-rerank text scrub.
        return SourceReadProjection(replace(
            snapshot, raw_assets=sources, raw_asset_chunks=chunks, knowledge_objects=objects,
            embedding_records=embeddings, relationships=[], overlays=[], metric_snapshots=[],
            retrieval_runs=[], rerank_records=[], task_contexts=[], quality_profiles=[],
            baselines=[item.model_copy(deep=True, update={
                "object_count": 0, "relationship_count": 0, "metric_snapshot_count": 0,
            }) for item in snapshot.baselines if item.project_id == scope.project_id],
        ), subjects, False)

    @staticmethod
    def _subject_ref(item) -> str:
        if item.chunk_ref:
            return f"raw_asset_chunk:{item.chunk_ref}"
        if item.object_ref:
            return f"context_object:{item.object_ref}"
        return f"raw_asset:{item.source_ref}" if item.source_ref else ""

    @staticmethod
    def _document_objects(snapshot: SystemImageProjectSnapshot, scope: SourceAccessScope) -> list[KnowledgeObject]:
        references = {item.document_reference.document_revision_id: item for item in snapshot.knowledge_objects if item.document_reference}
        if not references or not scope.binding_ids:
            return []
        model = SourceDocumentRevisionRecord
        with session_scope() as session:
            rows = session.scalars(select(model).where(model.project_id == scope.project_id, model.binding_id.in_(scope.binding_ids),
                model.document_revision_id.in_(references))).all()
        return [KnowledgeObject(id=f"DOC-{row.entity_id}", name=row.title, type=row.kind, branch="source_revision",
            confidence="source_observation", freshness="pinned", document_reference=KnowledgeDocumentReference(
                document_revision_id=row.document_revision_id, source_revision_id=row.source_revision_id)) for row in rows
            if references[row.document_revision_id].id == f"DOC-{row.entity_id}"
            and references[row.document_revision_id].document_reference.source_revision_id == row.source_revision_id]

    @staticmethod
    def _code_objects(snapshot: SystemImageProjectSnapshot, scope: SourceAccessScope) -> list[KnowledgeObject]:
        references = {item.id: item.code_reference for item in snapshot.knowledge_objects if item.code_reference}
        if not references or not scope.binding_ids:
            return []
        revision, alias = CodeEntityRevisionRecord, CodeObjectAliasRecord
        statement = select(
            alias, revision.payload, revision.payload_hash,
        ).select_from(revision).join(alias, and_(
            alias.project_id == revision.project_id, alias.binding_id == revision.binding_id,
            alias.source_revision_id == revision.source_revision_id,
            alias.entity_revision_id == revision.entity_revision_id, alias.entity_id == revision.entity_id,
        )).where(
            revision.project_id == scope.project_id, revision.binding_id.in_(scope.binding_ids),
            revision.entity_revision_id.in_([item.entity_revision_id for item in references.values()]),
            or_(alias.legacy_object_id.in_(references), alias.canonical_object_id.in_(references)),
        )
        with session_scope() as session:
            rows = session.execute(statement).all()
        result = {}
        for row, payload, payload_hash in rows:
            try:
                registered = verified_code_alias(row)
                if snapshot_digest(payload) != payload_hash:
                    raise ImageRevisionIntegrityError("Invalid code revision payload.")
            except ImageRevisionIntegrityError as exc:
                raise PlatformApplicationError("source_projection_integrity_failed",
                    "Source projection failed integrity verification.", status_code=502) from exc
            for object_id in {registered.legacy_object_id, registered.canonical_object_id} & references.keys():
                reference = references[object_id]
                if (reference.entity_id, reference.entity_revision_id, reference.source_revision_id) != (
                    registered.entity_id, registered.entity_revision_id, registered.source_revision_id,
                ) or payload.get("schema") not in {"nasus.code-entity-observation.v2", "nasus.code-entity-observation.v3"}:
                    continue
                symbol = payload["symbol"]
                # Reconstruct source-local fields without mutable cross-source labels.
                result[object_id] = KnowledgeObject(
                    id=object_id, name=f"{symbol['name']} ({symbol['relative_path']})", type=symbol["kind"],
                    branch="source_revision", confidence="source_observation", freshness="pinned",
                    code_reference=KnowledgeCodeReference(entity_id=registered.entity_id, entity_revision_id=registered.entity_revision_id,
                                                         source_revision_id=registered.source_revision_id),
                )
        return [result[key] for key in sorted(result)]
