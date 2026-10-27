from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from ...application.platform.tool_models import EventPayload
from ...application.system_image.document_projections import RegisteredDocument
from ...domain.system_image.evidence import DECODER_VERSION
from ...domain.system_image.document_components import COMPONENT_SCHEMA, COMPONENT_KINDS, validate_component_payload
from ...domain.system_image.source_snapshots import snapshot_digest
from .document_projection_models import (
    SourceDocumentIdentityRecord, SourceDocumentRevisionRecord, SourceDocumentEvidenceRecord, SourceDocumentExtractionRecord,
)
from .event_outbox_repository import EventOutboxRepository
from .source_evidence_repository import SourceEvidenceRepository
from .source_evidence_models import SourceEvidenceRecord
from .source_snapshot_models import SourceBindingRecord, SourceRevisionRecord
from .source_snapshot_repository import SourceSnapshotRepository
from .unit_of_work import session_scope


class DocumentProjectionRepository:
    @staticmethod
    def _extraction_header(row):
        return {key: getattr(row, key) for key in ("extraction_id", "project_id", "binding_id", "source_revision_id", "summary", "captured_at")}

    def list_extractions(self, project_id, source_revision_id, *, binding_ids, after_id, limit):
        if not 1 <= limit <= 101:
            raise ValueError("invalid extraction repository page")
        model = SourceDocumentExtractionRecord
        with session_scope() as session:
            rows = session.scalars(select(model).where(model.project_id == project_id, model.source_revision_id == source_revision_id,
                model.binding_id.in_(binding_ids), model.extraction_id > after_id).order_by(model.extraction_id).limit(limit))
            return [self._extraction_header(row) for row in rows]

    def get_extraction(self, project_id, extraction_id, *, binding_ids):
        with session_scope() as session:
            model = SourceDocumentExtractionRecord
            row = session.scalar(select(model).where(model.project_id == project_id, model.extraction_id == extraction_id,
                                                      model.binding_id.in_(binding_ids)))
            if row is None:
                raise KeyError("source document extraction not found")
            source = session.get(SourceRevisionRecord, row.source_revision_id)
            return {**self._extraction_header(row), "source_manifest_hash": source.manifest_hash}, row.report_ref, row.report_hash

    @staticmethod
    def _header(row):
        result = {key: getattr(row, key) for key in ("document_revision_id", "project_id", "binding_id", "source_revision_id",
            "entity_id", "title", "kind", "captured_at")}
        # Do not change legacy document query receipts by adding null fields.
        if row.parent_document_revision_id:
            result["parent_document_revision_id"] = row.parent_document_revision_id
        return result

    def list(self, project_id, source_revision_id, *, binding_ids, after_id, limit):
        if not 1 <= limit <= 101:
            raise ValueError("invalid document repository page")
        model = SourceDocumentRevisionRecord
        with session_scope() as session:
            rows = session.scalars(select(model).where(model.project_id == project_id,
                model.source_revision_id == source_revision_id, model.binding_id.in_(binding_ids),
                model.document_revision_id > after_id).order_by(model.document_revision_id).limit(limit))
            return [self._header(row) for row in rows]

    def get(self, project_id, document_revision_id, *, binding_ids):
        with session_scope() as session:
            row = session.scalar(select(SourceDocumentRevisionRecord).where(
                SourceDocumentRevisionRecord.project_id == project_id,
                SourceDocumentRevisionRecord.document_revision_id == document_revision_id,
                SourceDocumentRevisionRecord.binding_id.in_(binding_ids)))
            if row is None:
                raise KeyError("source document not found")
            source = session.get(SourceRevisionRecord, row.source_revision_id)
            evidence = session.scalars(select(SourceEvidenceRecord).join(SourceDocumentEvidenceRecord,
                SourceEvidenceRecord.evidence_id == SourceDocumentEvidenceRecord.evidence_id).where(
                SourceDocumentEvidenceRecord.document_revision_id == document_revision_id,
                SourceEvidenceRecord.project_id == project_id).order_by(SourceEvidenceRecord.start_line, SourceEvidenceRecord.end_line))
            return ({**self._header(row), "source_manifest_hash": source.manifest_hash}, row.payload_ref, row.payload_hash,
                [{"evidence_id": item.evidence_id, "start_line": item.start_line, "end_line": item.end_line,
                  "relative_path": item.relative_path, "snippet_hash": item.snippet_hash} for item in evidence])

    def record(self, source, items, *, manifest_hash, report_ref, report_hash, summary, captured_at):
        if source.source_type not in {"us_doc", "test_asset"}:
            raise ValueError("document source kind mismatch")
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, source.project_id)
            revision = session.scalar(select(SourceRevisionRecord).join(SourceBindingRecord,
                (SourceBindingRecord.project_id == SourceRevisionRecord.project_id)
                & (SourceBindingRecord.binding_id == SourceRevisionRecord.binding_id)).where(
                SourceBindingRecord.project_id == source.project_id, SourceBindingRecord.legacy_source_id == source.id,
                SourceBindingRecord.kind == source.source_type, SourceBindingRecord.external_identity == source.source_uri,
                SourceRevisionRecord.content_hash == source.content_hash, SourceRevisionRecord.manifest_ref == source.content_ref,
                SourceRevisionRecord.manifest_hash == manifest_hash))
            if revision is None:
                raise ValueError("document projection requires a matching immutable source revision")
            if len({snapshot_digest(item[0]) for item in items}) != len(items):
                raise ValueError("duplicate document identity in extraction")
            result, saved_parents = [], {}
            for key, payload, ref, digest in items:
                if (payload["project_id"] != source.project_id or payload["source_id"] != source.id
                        or payload["source_manifest_hash"] != manifest_hash or snapshot_digest(payload) != digest):
                    raise ValueError("document projection scope or digest mismatch")
                parent = None
                if payload.get("schema") == COMPONENT_SCHEMA or payload["kind"] in COMPONENT_KINDS:
                    pin = payload.get("parent", {})
                    saved = saved_parents.get((pin.get("identity_hash"), pin.get("payload_hash")))
                    if saved is None:
                        raise ValueError("component requires its exact parent in the same extraction")
                    parent, parent_payload = saved
                    expected_key = validate_component_payload(payload, parent_payload, pin["identity_hash"])
                    if expected_key != key:
                        raise ValueError("component identity does not match its source fields")
                identity = session.scalar(select(SourceDocumentIdentityRecord).where(
                    SourceDocumentIdentityRecord.project_id == source.project_id,
                    SourceDocumentIdentityRecord.binding_id == revision.binding_id,
                    SourceDocumentIdentityRecord.identity_hash == snapshot_digest(key)))
                if identity is None:
                    identity = SourceDocumentIdentityRecord(entity_id=str(uuid4()), project_id=source.project_id,
                        binding_id=revision.binding_id, identity_hash=snapshot_digest(key), identity_key=key, created_at=captured_at)
                    session.add(identity)
                    session.flush()
                elif identity.identity_key != key:
                    raise ValueError("document identity digest collision")
                row = session.scalar(select(SourceDocumentRevisionRecord).where(
                    SourceDocumentRevisionRecord.entity_id == identity.entity_id,
                    SourceDocumentRevisionRecord.source_revision_id == revision.source_revision_id,
                    SourceDocumentRevisionRecord.payload_hash == digest))
                if row is None:
                    row = SourceDocumentRevisionRecord(document_revision_id=str(uuid4()), project_id=source.project_id,
                        binding_id=revision.binding_id, source_revision_id=revision.source_revision_id,
                        entity_id=identity.entity_id, title=payload["title"], kind=payload["kind"],
                        payload_ref=ref, payload_hash=digest, captured_at=captured_at,
                        parent_document_revision_id=parent.document_revision_id if parent else None)
                    session.add(row)
                    session.flush()
                if row.parent_document_revision_id != (parent.document_revision_id if parent else None):
                    raise ValueError("source document parent revision mismatch")
                if parent is None:
                    saved_parents[(snapshot_digest(key), digest)] = row, payload
                prefix, separator, _ = revision.manifest_ref.rpartition("/manifests/")
                if not separator or "/system-image/source-snapshots/" not in prefix:
                    raise ValueError("source document requires an owned archive")
                spans = [(payload["locator"]["start_line"], payload["locator"]["end_line"], payload["snippet_hash"])]
                spans += [(field["start_line"], field["end_line"], field["snippet_hash"]) for field in payload["fields"]]
                evidence_ids = set()
                for start, end, snippet_hash in spans:
                    values = {"project_id": source.project_id, "binding_id": revision.binding_id,
                        "source_revision_id": revision.source_revision_id, "relative_path": payload["locator"]["relative_path"],
                        "start_line": start, "end_line": end, "precision": "exact", "file_hash": payload["source_file_hash"],
                        "snippet_hash": snippet_hash, "object_ref": f"{prefix}/files/{payload['source_file_hash'][7:]}",
                        "decoder_version": DECODER_VERSION, "extractor_version": payload["extractor_version"]}
                    evidence = SourceEvidenceRepository.append(session, values, captured_at=captured_at)
                    evidence_ids.add(evidence.evidence_id)
                    assoc = {"document_revision_id": row.document_revision_id, "evidence_id": evidence.evidence_id}
                    if session.get(SourceDocumentEvidenceRecord, assoc) is None:
                        session.add(SourceDocumentEvidenceRecord(**assoc, project_id=source.project_id,
                            binding_id=revision.binding_id, source_revision_id=revision.source_revision_id))
                        session.flush()
                result.append(RegisteredDocument(identity.entity_id, row.document_revision_id, revision.source_revision_id,
                    row.title, row.kind, tuple(sorted(evidence_ids)), payload))
            existing = session.scalar(select(SourceDocumentExtractionRecord).where(
                SourceDocumentExtractionRecord.project_id == source.project_id,
                SourceDocumentExtractionRecord.source_revision_id == revision.source_revision_id,
                SourceDocumentExtractionRecord.report_hash == report_hash))
            if existing is None:
                extraction_id = str(uuid4())
                session.add(SourceDocumentExtractionRecord(extraction_id=extraction_id, project_id=source.project_id,
                    binding_id=revision.binding_id, source_revision_id=revision.source_revision_id, report_ref=report_ref,
                    report_hash=report_hash, summary=summary, captured_at=captured_at))
                EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="system_image.documents.projected",
                    occurred_at=captured_at, correlation_id=source.project_id, entity_type="source_revision",
                    entity_id=revision.source_revision_id, entity_version=0, mutation_kind="append",
                    patch={"project_id": source.project_id, "extraction_id": extraction_id},
                    query_keys=[["system-image", source.project_id]]), session=session)
            return tuple(result)
