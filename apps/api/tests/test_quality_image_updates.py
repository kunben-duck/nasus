from __future__ import annotations

from copy import deepcopy

from apps.api.app.application.platform.project_models import ProjectCard, VersionSummary
from apps.api.app.application.quality_loop.quality_image_updates import (
    QualityImageUpdateApplicationService,
)
from apps.api.app.application.system_image.system_image_models import (
    BaselineRecord,
    ContextObjectOverlay,
    QualityMetricSnapshot,
)


class FakeQualityImageWorkspace:
    def __init__(self, *, ready: bool = True) -> None:
        self.project = ProjectCard(
            id="project_quality",
            name="Quality Project",
            code="QAP",
            summary="Quality project",
            status="active",
            risk="medium",
            progress=40,
            active_version="2026.Q3",
            blocked_items=0,
            pending_approvals=0,
            system_image_status="ready" if ready else "building",
        )
        self.baselines: list[BaselineRecord] = []
        self.overlays: list[ContextObjectOverlay] = []
        self.metrics: list[QualityMetricSnapshot] = []
        self.persist_count = 0

    def get_project(self, project_id: str) -> ProjectCard:
        assert project_id == self.project.id
        return self.project.model_copy(deep=True)

    def list_baselines(self, project_id: str) -> list[BaselineRecord]:
        return deepcopy(self.baselines)

    def replace_baselines(
        self,
        project_id: str,
        items: list[BaselineRecord],
    ) -> None:
        self.baselines = deepcopy(items)

    def list_context_object_overlays(
        self,
        project_id: str,
    ) -> list[ContextObjectOverlay]:
        return deepcopy(self.overlays)

    def replace_context_object_overlays(
        self,
        project_id: str,
        items: list[ContextObjectOverlay],
    ) -> None:
        self.overlays = deepcopy(items)

    def list_quality_metric_snapshots(
        self,
        project_id: str,
    ) -> list[QualityMetricSnapshot]:
        return deepcopy(self.metrics)

    def replace_quality_metric_snapshots(
        self,
        project_id: str,
        items: list[QualityMetricSnapshot],
    ) -> None:
        self.metrics = deepcopy(items)

    def persist_system_image(self, project_id: str) -> None:
        self.persist_count += 1


def version_provider(project_id: str) -> VersionSummary:
    return VersionSummary(
        id="version_quality",
        name="2026.Q3",
        status="active",
        branch_name="quality/2026-q3",
        us_total=1,
        us_closed=0,
        pending_runs=0,
        pending_approvals=0,
    )


def test_quality_image_update_uses_port_and_replaces_same_step_snapshot() -> None:
    workspace = FakeQualityImageWorkspace()
    workspace.baselines = [
        BaselineRecord(
            id="base_project_quality_official",
            project_id="project_quality",
            kind="official",
            status="ready",
            metric_snapshot_count=1,
            updated_at="2026-01-01T00:00:00+00:00",
        )
    ]
    workspace.metrics = [
        QualityMetricSnapshot(
            id="metric_project_quality_us_checkout_scope",
            project_id="project_quality",
            baseline_id="base_project_quality_official",
            version_id="version_quality",
            us_id="us_checkout",
            metric_group="test_quality",
            metrics={"scope_items": 1},
            captured_at="2026-01-01T00:00:00+00:00",
        ),
        QualityMetricSnapshot(
            id="metric_project_quality_us_other_cases",
            project_id="project_quality",
            baseline_id="base_project_quality_official",
            version_id="version_quality",
            us_id="us_other",
            metric_group="test_quality",
            metrics={"test_cases": 2},
            captured_at="2026-01-01T00:00:00+00:00",
        ),
    ]
    baseline_initializations: list[tuple[str, bool, str | None]] = []
    service = QualityImageUpdateApplicationService(
        workspace,
        version_provider,
        lambda project_id, *, ready, version_id=None: baseline_initializations.append(
            (project_id, ready, version_id)
        ),
    )

    refs = service.record_quality_image_update(
        "project_quality",
        "us_checkout",
        step="scope",
        metrics={"scope_items": 5},
        evidence_refs=["evidence:scope"],
    )

    assert refs == [
        "quality_metric:metric_project_quality_us_checkout_scope",
        "context_overlay:overlay_project_quality_us_checkout_scope",
    ]
    assert len(workspace.metrics) == 2
    assert workspace.metrics[0].metrics["scope_items"] == 5
    assert workspace.metrics[0].metrics["source"] == "quality_loop_tool"
    assert workspace.overlays[0].value_ref == (
        "quality_metric:metric_project_quality_us_checkout_scope"
    )
    assert workspace.baselines[0].metric_snapshot_count == 2
    assert workspace.persist_count == 1
    assert baseline_initializations == []


def test_quality_image_update_initializes_missing_baseline_through_port() -> None:
    workspace = FakeQualityImageWorkspace(ready=False)
    initializations: list[tuple[str, bool, str | None]] = []

    def initialize(
        project_id: str,
        *,
        ready: bool,
        version_id: str | None = None,
    ) -> None:
        initializations.append((project_id, ready, version_id))
        workspace.baselines = [
            BaselineRecord(
                id="base_project_quality_official",
                project_id=project_id,
                kind="official",
                status="draft",
                updated_at="2026-01-01T00:00:00+00:00",
            )
        ]

    service = QualityImageUpdateApplicationService(
        workspace,
        version_provider,
        initialize,
    )

    service.record_quality_image_update(
        "project_quality",
        "us_checkout",
        step="release",
        metrics={"score": 72},
        evidence_refs=["release:readiness"],
    )

    assert initializations == [("project_quality", False, "version_quality")]
    assert workspace.metrics[0].metric_group == "release_readiness"
    assert workspace.persist_count == 1
