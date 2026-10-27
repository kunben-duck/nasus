from __future__ import annotations

import json
from pathlib import PurePosixPath
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import and_, or_, select, text

from ...application.platform.tool_models import EventPayload
from ...application.system_image.system_image_models import RawAssetRecord
from ...application.system_image.code_analysis_queries import CodeAnalysisSummary, CodeSourceRevisionSummary
from ...domain.system_image.source_snapshots import snapshot_digest
from ...domain.system_image.code_provider import validate_projection_payload
from ...domain.system_image.code_observation_archive import validate_observation_pin
from .code_analysis_models import CodeAnalysisRecord
from .event_outbox_repository import EventOutboxRepository
from .source_snapshot_models import SourceBindingRecord, SourceRevisionRecord
from .unit_of_work import session_scope


class CodeAnalysisRepository:
    def list_source_revisions(self, project_id: str, *, binding_ids: frozenset[str],
                              after_id: str, limit: int) -> list[CodeSourceRevisionSummary]:
        if not 1 <= limit <= 101:
            raise ValueError("invalid repository revision page size")
        revision, binding = SourceRevisionRecord, SourceBindingRecord
        scope = (revision.project_id == project_id, revision.binding_id.in_(binding_ids), binding.kind == "code")
        query = select(revision, binding.legacy_source_id, binding.external_identity).join(binding, and_(
            binding.project_id == revision.project_id, binding.binding_id == revision.binding_id,
        )).where(*scope)
        with session_scope() as session:
            if after_id:
                anchor = session.execute(query.where(revision.source_revision_id == after_id)).first()
                if anchor is None:
                    raise KeyError("source revision cursor is not available")
                query = query.where(or_(revision.acquired_at < anchor[0].acquired_at, and_(
                    revision.acquired_at == anchor[0].acquired_at, revision.source_revision_id < after_id,
                )))
            rows = session.execute(query.order_by(revision.acquired_at.desc(), revision.source_revision_id.desc()).limit(limit)).all()
            # Labels omit credentials, query strings, storage URLs and parent directories.
            return [CodeSourceRevisionSummary(
                row.project_id, source_id, PurePosixPath(urlsplit(identity).path).name[:240] or source_id,
                row.binding_id, row.source_revision_id, row.external_revision, row.acquired_at, row.file_count,
            ) for row, source_id, identity in rows]

    @staticmethod
    def _summary(row, metadata: dict) -> CodeAnalysisSummary:
        return CodeAnalysisSummary(
            row.analysis_id, row.project_id, row.binding_id, row.source_revision_id, row.report_hash, row.recorded_at,
            metadata["provider"], metadata["provider_version"], metadata["algorithm"], metadata["scope"],
            metadata["raw_inventory_available"], metadata["summary"], metadata.get("projection"),
            metadata.get("observation_summary") or (
                metadata["observation_archive"]["summary"] if metadata.get("observation_archive") else None),
        )

    def list_for_revision(self, project_id: str, source_revision_id: str, *,
                          binding_ids: frozenset[str], after_id: str, limit: int) -> list[CodeAnalysisSummary]:
        if not 1 <= limit <= 101:
            raise ValueError("invalid repository page size")
        model = CodeAnalysisRecord
        metadata = ("provider", "provider_version", "algorithm", "scope", "raw_inventory_available", "summary", "projection")
        with session_scope() as session:
            # Never hydrate file paths or structure facts while listing reports.
            rows = session.execute(select(
                model.analysis_id, model.project_id, model.binding_id, model.source_revision_id,
                model.report_hash, model.recorded_at, *(model.payload[key].label(key) for key in metadata),
                model.payload["observation_archive"]["summary"].label("observation_summary"),
            ).where(model.project_id == project_id, model.source_revision_id == source_revision_id,
                    model.binding_id.in_(binding_ids), model.analysis_id > after_id)
                .order_by(model.analysis_id).limit(limit)).all()
            return [self._summary(row, {key: getattr(row, key) for key in (*metadata, "observation_summary")}) for row in rows]

    def read(self, project_id: str, source_revision_id: str, analysis_id: str, *,
             binding_ids: frozenset[str]) -> tuple[CodeAnalysisSummary, dict]:
        with session_scope() as session:
            row = session.scalar(select(CodeAnalysisRecord).where(
                CodeAnalysisRecord.project_id == project_id, CodeAnalysisRecord.source_revision_id == source_revision_id,
                CodeAnalysisRecord.analysis_id == analysis_id, CodeAnalysisRecord.binding_id.in_(binding_ids),
            ))
            if row is None:
                raise KeyError("code analysis not found")
            return self._summary(row, row.payload), row.payload

    def record(self, source: RawAssetRecord, payload: dict, *, captured_at: str) -> str:
        if (source.source_type != "code" or payload.get("schema") not in {"nasus.code-analysis.v1", "nasus.code-analysis.v2", "nasus.code-analysis.v3"}
                or payload.get("project_id") != source.project_id or payload.get("source_id") != source.id):
            raise ValueError("code analysis scope mismatch")
        if payload["schema"] == "nasus.code-analysis.v3":
            validate_observation_pin(payload.get("observation_archive"))
            if payload.get("projection") is not None:
                validate_projection_payload(payload["projection"])
        elif payload.get("observation_archive") is not None:
            raise ValueError("legacy code analysis cannot acquire archived observations")
        elif payload["schema"] == "nasus.code-analysis.v2":
            validate_projection_payload(payload.get("projection"))
        elif payload.get("projection") is not None:
            raise ValueError("legacy code analysis cannot acquire a provider declaration")
        if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 16 * 1024 * 1024:
            raise ValueError("code analysis report exceeds size limit")
        digest = snapshot_digest(payload)
        with session_scope() as session:
            session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {
                "key": f"nasus:code-analysis:{source.project_id}",
            })
            revision = session.scalar(select(SourceRevisionRecord).join(SourceBindingRecord, (
                (SourceRevisionRecord.project_id == SourceBindingRecord.project_id)
                & (SourceRevisionRecord.binding_id == SourceBindingRecord.binding_id)
            )).where(
                SourceBindingRecord.project_id == source.project_id, SourceBindingRecord.legacy_source_id == source.id,
                SourceBindingRecord.external_identity == source.source_uri, SourceBindingRecord.kind == "code",
                SourceRevisionRecord.manifest_ref == source.content_ref,
                SourceRevisionRecord.content_hash == source.content_hash,
                SourceRevisionRecord.manifest_hash == payload["source_manifest_hash"],
                SourceRevisionRecord.external_revision == payload["external_revision"],
            ))
            if revision is None:
                raise ValueError("code analysis requires a matching immutable source revision")
            existing = session.scalar(select(CodeAnalysisRecord).where(
                CodeAnalysisRecord.source_revision_id == revision.source_revision_id, CodeAnalysisRecord.report_hash == digest,
            ))
            if existing is not None:
                if snapshot_digest(existing.payload) != digest:
                    raise ValueError("code analysis digest collision")
                return existing.analysis_id
            analysis_id = str(uuid4())
            session.add(CodeAnalysisRecord(
                analysis_id=analysis_id, project_id=source.project_id, binding_id=revision.binding_id,
                source_revision_id=revision.source_revision_id, report_hash=digest, payload=payload, recorded_at=captured_at,
            ))
            EventOutboxRepository().append(EventPayload(
                event_id=str(uuid4()), event_type="system_image.code_analysis.recorded", occurred_at=captured_at,
                correlation_id=source.project_id, entity_type="source_revision", entity_id=revision.source_revision_id,
                entity_version=0, mutation_kind="append",
                patch={"project_id": source.project_id, "analysis_id": analysis_id},
                query_keys=[["system-image", source.project_id]],
            ), session=session)
            return analysis_id
