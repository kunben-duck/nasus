from sqlalchemy import select

from ...application.system_image.source_deltas import SourceRevisionReadTarget
from ...domain.system_image.source_delta import SourceRevisionPin
from .source_snapshot_models import SourceBindingRecord, SourceRevisionRecord
from .unit_of_work import session_scope


class SourceDeltaRepository:
    def get_pair(self, project_id, before_id, after_id, *, binding_ids):
        with session_scope() as session:
            rows = session.execute(select(SourceRevisionRecord, SourceBindingRecord).join(
                SourceBindingRecord, SourceBindingRecord.binding_id == SourceRevisionRecord.binding_id).where(
                SourceRevisionRecord.project_id == project_id, SourceBindingRecord.project_id == project_id,
                SourceRevisionRecord.source_revision_id.in_({before_id, after_id}),
                SourceRevisionRecord.binding_id.in_(binding_ids))).all()
            by_id = {revision.source_revision_id: SourceRevisionReadTarget(
                SourceRevisionPin(project_id, binding.binding_id, revision.source_revision_id, binding.kind,
                    revision.external_revision, revision.manifest_hash, revision.content_hash),
                binding.legacy_source_id, revision.manifest_ref, revision.policy_version,
                revision.file_count, revision.byte_count) for revision, binding in rows}
            if set(by_id) != {before_id, after_id}:
                raise KeyError("source delta revisions not available")
            return by_id[before_id], by_id[after_id]
