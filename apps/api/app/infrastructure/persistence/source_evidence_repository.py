from __future__ import annotations

from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...application.system_image.evidence_queries import EvidenceReadTarget
from ...domain.system_image.evidence import EvidenceLocator, SourceEvidence, EvidencePageTooLarge, EvidenceIntegrityError
from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from ...domain.system_image.source_snapshots import snapshot_digest
from .code_entity_models import CodeEntityRevisionRecord
from .code_alias_models import CodeObjectAliasRecord
from .code_alias_repository import verified_code_alias
from .source_evidence_models import SourceEvidenceRecord, CodeEntityEvidenceRecord
from .source_snapshot_models import SourceBindingRecord, SourceRevisionRecord
from .unit_of_work import session_scope


class SourceEvidenceRepository:
    @staticmethod
    def append_for_entity(session: Session, revision: SourceRevisionRecord, entity: CodeEntityRevisionRecord) -> None:
        payload = entity.payload
        prefix, separator, _ = revision.manifest_ref.rpartition("/manifests/")
        if (not separator or "/system-image/source-snapshots/" not in prefix
                or payload.get("schema") not in {"nasus.code-entity-observation.v2", "nasus.code-entity-observation.v3"}):
            # Do not synthesize verified evidence for legacy locator conventions.
            return
        values = {
            "project_id": revision.project_id, "binding_id": revision.binding_id,
            "source_revision_id": revision.source_revision_id,
            "file_hash": payload["source_file_hash"],
            "object_ref": f"{prefix}/files/{payload['source_file_hash'][7:]}",
            "decoder_version": payload["decoder_version"],
            "extractor_version": payload["schema"] + "/" + payload["symbol"]["schema_version"],
        }
        locators = [{**payload["locator"], "decoded_snippet_hash": payload["decoded_snippet_hash"]}]
        if payload["schema"] == "nasus.code-entity-observation.v3":
            locators.extend(payload["supporting_locators"])
        for locator in locators:
            row = SourceEvidenceRepository.append(session, {**values,
                **{key: locator[key] for key in ("relative_path", "start_line", "end_line", "precision")},
                "snippet_hash": locator["decoded_snippet_hash"]}, captured_at=entity.captured_at)
            key = {"entity_revision_id": entity.entity_revision_id, "evidence_id": row.evidence_id}
            if session.get(CodeEntityEvidenceRecord, key) is None:
                session.add(CodeEntityEvidenceRecord(**key, project_id=revision.project_id,
                                                    binding_id=revision.binding_id, source_revision_id=revision.source_revision_id))

    @staticmethod
    def append(session: Session, values: dict, *, captured_at: str) -> SourceEvidenceRecord:
        digest = snapshot_digest(values)
        row = session.scalar(select(SourceEvidenceRecord).where(
            SourceEvidenceRecord.project_id == values["project_id"],
            SourceEvidenceRecord.binding_id == values["binding_id"],
            SourceEvidenceRecord.source_revision_id == values["source_revision_id"],
            SourceEvidenceRecord.identity_hash == digest,
        ))
        if row is None:
            row = SourceEvidenceRecord(evidence_id=str(uuid4()), identity_hash=digest, captured_at=captured_at, **values)
            SourceEvidenceRepository._domain(row)
            session.add(row)
            session.flush()
        return row

    def get(self, project_id: str, evidence_id: str) -> EvidenceReadTarget:
        return self.get_many(project_id, (evidence_id,))[0]

    def get_many(self, project_id: str, evidence_ids: tuple[str, ...]) -> list[EvidenceReadTarget]:
        if not 1 <= len(evidence_ids) <= 512 or len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("invalid evidence selection")
        with session_scope() as session:
            result = session.execute(select(SourceEvidenceRecord, SourceRevisionRecord, SourceBindingRecord)
                .join(SourceRevisionRecord, SourceRevisionRecord.source_revision_id == SourceEvidenceRecord.source_revision_id)
                .join(SourceBindingRecord, SourceBindingRecord.binding_id == SourceEvidenceRecord.binding_id).where(
                SourceEvidenceRecord.project_id == project_id, SourceEvidenceRecord.evidence_id.in_(evidence_ids),
                SourceRevisionRecord.project_id == project_id, SourceBindingRecord.project_id == project_id,
                SourceRevisionRecord.binding_id == SourceEvidenceRecord.binding_id,
            )).all()
            if len(result) != len(evidence_ids):
                raise KeyError("evidence not found")
            return [EvidenceReadTarget(self._domain(row), binding.legacy_source_id,
                revision.manifest_ref, revision.manifest_hash, revision.content_hash) for row, revision, binding in result]

    def list_for_alias(self, project_id: str, source_revision_id: str, object_id: str, *,
                       entity_revision_id: str | None = None) -> list[SourceEvidence]:
        with session_scope() as session:
            revision = session.scalar(select(SourceRevisionRecord).where(
                SourceRevisionRecord.project_id == project_id, SourceRevisionRecord.source_revision_id == source_revision_id,
            ))
            if revision is None:
                raise KeyError("source revision not found")
            aliases = select(CodeObjectAliasRecord).where(
                CodeObjectAliasRecord.project_id == project_id,
                CodeObjectAliasRecord.source_revision_id == source_revision_id,
                or_(CodeObjectAliasRecord.legacy_object_id == object_id, CodeObjectAliasRecord.canonical_object_id == object_id),
            )
            if entity_revision_id is not None:
                aliases = aliases.where(CodeObjectAliasRecord.entity_revision_id == entity_revision_id)
            records = session.scalars(aliases.limit(513)).all()
            if len(records) > 512:
                raise EvidencePageTooLarge("too many alias registrations; no partial evidence was returned")
            try:
                mappings = {verified_code_alias(row).entity_revision_id for row in records}
            except ImageRevisionIntegrityError as exc:
                raise EvidenceIntegrityError("Code evidence alias failed integrity verification.") from exc
            if len(mappings) > 1:
                raise EvidenceIntegrityError("Code alias requires an explicit entity revision.")
            evidence_ids = select(CodeEntityEvidenceRecord.evidence_id).where(
                CodeEntityEvidenceRecord.project_id == project_id,
                CodeEntityEvidenceRecord.source_revision_id == source_revision_id,
                CodeEntityEvidenceRecord.entity_revision_id.in_(mappings),
            )
            rows = session.scalars(select(SourceEvidenceRecord).where(
                SourceEvidenceRecord.project_id == project_id, SourceEvidenceRecord.evidence_id.in_(evidence_ids),
            ).order_by(SourceEvidenceRecord.evidence_id).limit(201)).all()
            if len(rows) > 200:
                raise EvidencePageTooLarge("too many evidence variants for this alias")
            return [self._domain(row) for row in rows]

    @staticmethod
    def _domain(row: SourceEvidenceRecord) -> SourceEvidence:
        return SourceEvidence(
            row.evidence_id, row.project_id, row.binding_id, row.source_revision_id,
            EvidenceLocator(row.relative_path, row.start_line, row.end_line, row.precision),
            row.file_hash, row.snippet_hash, row.object_ref, row.decoder_version,
            row.extractor_version, row.captured_at,
        )
