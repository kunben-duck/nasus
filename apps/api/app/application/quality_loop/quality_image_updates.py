from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from .ports import QualityImageWorkspacePort
from ..platform.project_models import VersionSummary
from ..system_image.system_image_models import ContextObjectOverlay, QualityMetricSnapshot


class ActiveQualityImageVersionProvider(Protocol):
    def __call__(self, project_id: str) -> VersionSummary:
        """Return the active version or create the default quality-loop version."""


class QualityImageBaselineInitializer(Protocol):
    def __call__(
        self,
        project_id: str,
        *,
        ready: bool,
        version_id: str | None = None,
    ) -> None:
        """Initialize the official baseline when no system-image state exists."""


class QualityImageUpdateApplicationService:
    """Writes quality-loop metric updates into the system image read model.

    Quality-loop steps decide which metrics were produced. This service owns the
    cross-context write mechanics: quality metric snapshots, context overlays,
    baseline metric counters, and system-image persistence.
    """

    def __init__(
        self,
        workspace: QualityImageWorkspacePort,
        active_version_provider: ActiveQualityImageVersionProvider,
        baseline_initializer: QualityImageBaselineInitializer,
    ) -> None:
        self._workspace = workspace
        self._active_version_provider = active_version_provider
        self._baseline_initializer = baseline_initializer

    def record_quality_image_update(
        self,
        project_id: str,
        us_id: str,
        *,
        step: str,
        metrics: dict[str, object],
        evidence_refs: list[str],
    ) -> list[str]:
        version = self._active_version_provider(project_id)
        baseline_id = self._baseline_id(project_id, version.id)
        captured_at = self._now()
        metric_group = "release_readiness" if step == "release" else "test_quality"
        metric_id = f"metric_{project_id}_{us_id}_{step}"
        overlay_id = f"overlay_{project_id}_{us_id}_{step}"

        metric = QualityMetricSnapshot(
            id=metric_id,
            project_id=project_id,
            baseline_id=baseline_id,
            version_id=version.id,
            us_id=us_id,
            metric_group=metric_group,
            metrics={
                **metrics,
                "quality_loop_step": step,
                "source": "quality_loop_tool",
            },
            evidence_refs=evidence_refs,
            captured_at=captured_at,
        )
        metric_snapshots = [
            metric,
            *[
                existing
                for existing in self._workspace.list_quality_metric_snapshots(project_id)
                if existing.id != metric_id
            ],
        ]
        self._workspace.replace_quality_metric_snapshots(
            project_id,
            metric_snapshots,
        )

        overlay = ContextObjectOverlay(
            id=overlay_id,
            project_id=project_id,
            baseline_id=baseline_id,
            object_id=us_id,
            field_path=f"quality_loop.{step}",
            operation="replace",
            value_ref=f"quality_metric:{metric_id}",
            source_refs=evidence_refs,
            status="candidate",
        )
        overlays = [
            overlay,
            *[
                existing
                for existing in self._workspace.list_context_object_overlays(project_id)
                if existing.id != overlay_id
            ],
        ]
        self._workspace.replace_context_object_overlays(project_id, overlays)

        baselines = self._workspace.list_baselines(project_id)
        for baseline in baselines:
            if baseline.id == baseline_id:
                baseline.metric_snapshot_count = len(metric_snapshots)
                baseline.updated_at = captured_at
                break
        self._workspace.replace_baselines(project_id, baselines)
        self._workspace.persist_system_image(project_id)
        return [f"quality_metric:{metric_id}", f"context_overlay:{overlay_id}"]

    def _baseline_id(self, project_id: str, version_id: str) -> str:
        if not self._workspace.list_baselines(project_id):
            project = self._workspace.get_project(project_id)
            self._baseline_initializer(
                project_id,
                ready=project.system_image_status == "ready",
                version_id=version_id,
            )
        return self._workspace.list_baselines(project_id)[0].id

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


__all__ = [
    "ActiveQualityImageVersionProvider",
    "QualityImageBaselineInitializer",
    "QualityImageUpdateApplicationService",
]
