from __future__ import annotations

from typing import Any, Protocol

from .quality_models import ReleaseReadiness
from .release_readiness_port import ReleaseReadinessRepository
from ...domain.quality_loop.release_readiness import (
    ReleaseReadinessEvidence,
    decide_release_readiness,
)


class ActiveReleaseVersionProvider(Protocol):
    def __call__(self, project_id: str) -> Any:
        """Return the active version or create the default quality-loop version."""


class QualityReleaseReadinessApplicationService:
    """Write-side boundary for release readiness facts and project risk sync."""

    def __init__(
        self,
        repository: ReleaseReadinessRepository,
        active_version_provider: ActiveReleaseVersionProvider,
    ) -> None:
        self._repository = repository
        self._active_version_provider = active_version_provider

    def upsert_release_readiness(self, project_id: str, us_id: str) -> ReleaseReadiness:
        version = self._active_version_provider(project_id)
        snapshot = self._repository.load_snapshot(
            project_id=project_id,
            us_id=us_id,
            version_id=version.id,
        )
        decision = decide_release_readiness(
            ReleaseReadinessEvidence(
                run_statuses=snapshot.run_statuses,
                evidence_types=snapshot.evidence_types,
                asset_part_statuses=snapshot.asset_part_statuses,
                task_context_readiness=snapshot.task_context_readiness,
                task_context_confidence=snapshot.task_context_confidence,
                missing_context_count=snapshot.missing_context_count,
                quality_profile_coverage=snapshot.quality_profile_coverage,
                quality_profile_confidence=snapshot.quality_profile_confidence,
                fallback_generated_parts=snapshot.fallback_generated_parts,
                open_failures=snapshot.open_failures,
                approvals_open=snapshot.approvals_open,
                pending_merge=snapshot.pending_merge,
            )
        )
        release = ReleaseReadiness(**decision.to_api_kwargs(version_id=version.id))
        self._repository.save_assessment(
            project_id=project_id,
            readiness=release,
            progress_floor=decision.progress_floor,
            blockers=decision.blockers,
        )
        return release


__all__ = ["ActiveReleaseVersionProvider", "QualityReleaseReadinessApplicationService"]
