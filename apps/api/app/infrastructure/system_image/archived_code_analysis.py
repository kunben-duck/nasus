from __future__ import annotations

from typing import Sequence

from ...application.system_image.code_analysis_inventory import build_code_analysis_inventory
from ...application.system_image.code_observations import received_code_observations
from ...application.system_image.source_ports import CodeIntelligenceResult, SourceTextUnit
from ...application.system_image.system_image_models import RawAssetRecord
from ..persistence.code_analysis_repository import CodeAnalysisRepository
from .source_snapshot_archive import SourceSnapshotArchive
from .code_observation_artifacts import ArchivedCodeObservations


class ArchivedCodeAnalysisRecorder:
    def __init__(self, archive: SourceSnapshotArchive, repository: CodeAnalysisRepository, *,
                 max_files: int, max_bytes: int, max_file_bytes: int) -> None:
        self.archive, self.repository = archive, repository
        self.max_files, self.max_bytes, self.max_file_bytes = max_files, max_bytes, max_file_bytes

    def record(self, source: RawAssetRecord, result: CodeIntelligenceResult,
               units: Sequence[SourceTextUnit], *, captured_at: str) -> str | None:
        if not self.archive.owns_ref(source.content_ref):
            return None
        manifest = self.archive.read_manifest(
            source.content_ref, project_id=source.project_id, source_id=source.id,
            content_hash=source.content_hash, max_files=self.max_files,
            max_bytes=self.max_bytes, max_file_bytes=self.max_file_bytes,
        )
        payload = build_code_analysis_inventory(manifest, result, units)
        pin = ArchivedCodeObservations(self.archive.storage).put(received_code_observations(manifest, result))
        payload.update(schema="nasus.code-analysis.v3", observation_archive=pin)
        return self.repository.record(source, payload, captured_at=captured_at)
