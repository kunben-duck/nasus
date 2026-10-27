from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Optional, TYPE_CHECKING

from ...domain.system_image.image_revision import ImageRevisionSummary
from ...domain.system_image.frozen_projection import require_frozen_projection
from ...domain.system_image.source_snapshots import CapturedSourceManifest
from .context_extraction import ContextExtractionService, ExtractedContext
from .image_revision_ports import ImageCandidatePort
from .source_snapshot_ports import SourceSnapshotRepositoryPort
from .system_image_models import RawAssetRecord

if TYPE_CHECKING:
    from .structure_builds import StructureBuildCommit


@dataclass(frozen=True)
class PreparedImageCandidate:
    sources: tuple[RawAssetRecord, ...]
    context: ExtractedContext
    revision: ImageRevisionSummary


class ImageCandidatePreparation:
    """No mutable workspace access: safe to execute outside the HTTP event loop."""

    def __init__(self, snapshots: SourceSnapshotRepositoryPort, extraction: ContextExtractionService, candidates: ImageCandidatePort):
        self.snapshots, self.extraction, self.candidates = snapshots, extraction, candidates

    def prepare(self, manifest: CapturedSourceManifest, *, project_name: str, baseline_id: str,
                version_id: Optional[str], invocation_id: Optional[str], recorded_at: str,
                check_phase: Optional[Callable[[], None]] = None,
                build_commit: Optional[StructureBuildCommit] = None) -> PreparedImageCandidate:
        if check_phase:
            check_phase()
        sources = self.snapshots.materialization_sources(manifest)
        if check_phase:
            check_phase()
        context = self.extraction.extract(project_id=manifest.project_id, project_name=project_name,
            baseline_id=baseline_id, sources=sources, version_id=version_id, captured_at=recorded_at,
            check_phase=check_phase, invocation_id=invocation_id, source_manifest=manifest)
        require_frozen_projection(manifest, baseline_id, objects=context.objects,
            relationships=context.relationships, metrics=context.metrics)
        if check_phase:
            check_phase()
        extra = {"build_commit": replace(build_commit, code_extractions=context.code_extractions)} if build_commit is not None else {}
        revision = self.candidates.freeze(manifest, baseline_id, objects=context.objects, relationships=context.relationships,
                                          invocation_id=invocation_id, recorded_at=recorded_at, **extra)
        return PreparedImageCandidate(tuple(sources), context, revision)
