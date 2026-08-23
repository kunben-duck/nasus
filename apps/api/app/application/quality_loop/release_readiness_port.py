from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .quality_models import ReleaseReadiness


@dataclass(frozen=True)
class ReleaseFailureFact:
    failure_kind: str
    summary: str
    fallback_to_human: bool


@dataclass(frozen=True)
class ReleaseReadinessSnapshot:
    version_id: str
    run_statuses: tuple[str, ...] = ()
    evidence_types: tuple[str, ...] = ()
    asset_part_statuses: tuple[tuple[str, str], ...] = ()
    task_context_readiness: str | None = None
    task_context_confidence: float = 0
    missing_context_count: int = 0
    quality_profile_coverage: int = 0
    quality_profile_confidence: float = 0
    fallback_generated_parts: int = 0
    open_failures: tuple[ReleaseFailureFact, ...] = ()
    approvals_open: int = 0
    pending_merge: int = 0


class ReleaseReadinessRepository(Protocol):
    def load_snapshot(
        self,
        *,
        project_id: str,
        us_id: str,
        version_id: str,
    ) -> ReleaseReadinessSnapshot:
        """Load the authoritative evidence snapshot used by release policy."""

    def save_assessment(
        self,
        *,
        project_id: str,
        readiness: ReleaseReadiness,
        progress_floor: int,
        blockers: int,
    ) -> None:
        """Persist release readiness and synchronized project risk atomically."""


__all__ = [
    "ReleaseFailureFact",
    "ReleaseReadinessRepository",
    "ReleaseReadinessSnapshot",
]
