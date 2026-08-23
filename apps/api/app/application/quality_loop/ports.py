from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .quality_models import (
    AssetLane,
    ExecutionEvidence,
    FailureReport,
    QualityAssetPack,
    ReleaseDecision,
    ReleaseReadiness,
    RunDetail,
    USItem,
)
from ..platform.project_models import ProjectCard, VersionSummary
from ..system_image.system_image_models import (
    BaselineRecord,
    ContextObjectOverlay,
    QualityProfile,
    QualityMetricSnapshot,
    TaskContext,
)


class ProjectVersionWorkspacePort(Protocol):
    """Project/version/US facts required by quality-loop onboarding use cases."""

    def initialize_project(self, project: ProjectCard) -> None:
        ...

    def has_project(self, project_id: str) -> bool:
        ...

    def get_project(self, project_id: str) -> ProjectCard:
        ...

    def save_project(self, project: ProjectCard) -> None:
        ...

    def list_versions(self, project_id: str) -> list[VersionSummary]:
        ...

    def prepend_version(
        self,
        project_id: str,
        version: VersionSummary,
    ) -> None:
        ...

    def save_version(
        self,
        project_id: str,
        version: VersionSummary,
    ) -> None:
        ...

    def list_us_items(
        self,
        project_id: str,
        version_id: str | None = None,
    ) -> list[USItem]:
        ...

    def save_us_items(
        self,
        project_id: str,
        version_id: str | None,
        items: list[USItem],
    ) -> None:
        ...

    def save_us_item(
        self,
        project_id: str,
        version_id: str | None,
        item: USItem,
    ) -> None:
        ...

    def save_release_readiness(
        self,
        project_id: str,
        readiness: ReleaseReadiness,
    ) -> None:
        ...

    def conversation_project_id(self, conversation_id: str | None) -> str | None:
        ...

    def has_indexed_system_image_evidence(self, project_id: str) -> bool:
        ...


class QualityLoopContextReadPort(Protocol):
    """Current system-image context consumed while starting a quality task."""

    def current_task_context(
        self,
        project_id: str,
        us_id: str | None = None,
    ) -> TaskContext | None:
        ...

    def current_quality_profile(
        self,
        project_id: str,
        us_id: str | None = None,
    ) -> QualityProfile | None:
        ...


class QualityLoopContextWorkspacePort(Protocol):
    """Read-only quality context projection used by application queries."""

    def list_task_contexts(self, project_id: str) -> list[TaskContext]:
        ...

    def list_quality_profiles(self, project_id: str) -> list[QualityProfile]:
        ...

    def get_quality_asset_pack(
        self,
        project_id: str,
        us_id: str,
    ) -> QualityAssetPack | None:
        ...

    def list_quality_asset_packs(self, project_id: str) -> list[QualityAssetPack]:
        ...

    def list_us_items(self, project_id: str) -> list[USItem]:
        ...

    def project_id_for_us(self, us_id: str) -> str | None:
        ...

    def list_asset_lanes(self, us_id: str) -> list[AssetLane]:
        ...


@dataclass(frozen=True)
class QualityLoopConversationScope:
    project_id: str | None
    us_id: str | None
    space_type: str
    space_id: str


class QualityLoopScopeWorkspacePort(Protocol):
    """Read-only ownership facts used to resolve governed tool scope."""

    def conversation_scope(
        self,
        conversation_id: str | None,
    ) -> QualityLoopConversationScope | None:
        ...

    def project_id_for_us(self, us_id: str) -> str | None:
        ...

    def first_us_id(self, project_id: str) -> str | None:
        ...

    def project_id_for_run(self, run_id: str) -> str | None:
        ...

    def list_run_details(self, project_id: str) -> list[RunDetail]:
        ...

    def us_id_for_run_evidence(
        self,
        project_id: str,
        run_id: str,
    ) -> str | None:
        ...


class QualityLoopReleaseDecisionReadPort(Protocol):
    """Durable release-decision facts consumed by governance."""

    def find_release_decision(
        self,
        project_id: str,
        us_id: str | None = None,
        version_id: str | None = None,
    ) -> ReleaseDecision | None:
        ...


class QualityAssetProgressWorkspacePort(Protocol):
    """Quality lane and US progress facts mutated by quality-step use cases."""

    def list_asset_lanes(self, us_id: str) -> list[AssetLane]:
        ...

    def ensure_asset_lanes(
        self,
        project_id: str,
        us_id: str,
        lanes: list[AssetLane],
    ) -> None:
        ...

    def save_asset_lane(
        self,
        project_id: str,
        us_id: str,
        lane: AssetLane,
    ) -> None:
        ...

    def get_us_item(self, project_id: str, us_id: str) -> USItem | None:
        ...

    def save_us_item(
        self,
        project_id: str,
        item: USItem,
    ) -> None:
        ...


class QualityAssetPackWorkspacePort(Protocol):
    """QualityAssetPack aggregate persistence used by write-side use cases."""

    def get_quality_asset_pack(
        self,
        project_id: str,
        us_id: str,
    ) -> QualityAssetPack | None:
        ...

    def save_quality_asset_pack(self, pack: QualityAssetPack) -> None:
        ...


class QualityAssetPackReadPort(Protocol):
    """Durable current QualityAssetPack projection used for execution."""

    def get_quality_asset_pack(
        self,
        project_id: str,
        us_id: str,
    ) -> QualityAssetPack | None:
        ...


class QualityExecutionEvidenceReadPort(Protocol):
    """Durable execution evidence used by quality planning and release."""

    def list_execution_evidence(
        self,
        project_id: str,
    ) -> list[ExecutionEvidence]:
        ...


class QualityFailureWorkspacePort(Protocol):
    """Durable failure-report aggregate and failed-run persistence boundary."""

    def list_failure_reports(self, project_id: str) -> list[FailureReport]:
        ...

    def save_failure_analysis(
        self,
        project_id: str,
        run: RunDetail,
        reports: list[FailureReport],
    ) -> None:
        ...


class QualityImageWorkspacePort(Protocol):
    """Minimal system-image boundary used by quality-loop metric updates."""

    def get_project(self, project_id: str) -> ProjectCard:
        ...

    def list_baselines(self, project_id: str) -> list[BaselineRecord]:
        ...

    def replace_baselines(
        self,
        project_id: str,
        items: list[BaselineRecord],
    ) -> None:
        ...

    def list_context_object_overlays(
        self,
        project_id: str,
    ) -> list[ContextObjectOverlay]:
        ...

    def replace_context_object_overlays(
        self,
        project_id: str,
        items: list[ContextObjectOverlay],
    ) -> None:
        ...

    def list_quality_metric_snapshots(
        self,
        project_id: str,
    ) -> list[QualityMetricSnapshot]:
        ...

    def replace_quality_metric_snapshots(
        self,
        project_id: str,
        items: list[QualityMetricSnapshot],
    ) -> None:
        ...

    def persist_system_image(self, project_id: str) -> None:
        ...


__all__ = [
    "ProjectVersionWorkspacePort",
    "QualityAssetPackReadPort",
    "QualityAssetPackWorkspacePort",
    "QualityAssetProgressWorkspacePort",
    "QualityExecutionEvidenceReadPort",
    "QualityFailureWorkspacePort",
    "QualityImageWorkspacePort",
    "QualityLoopConversationScope",
    "QualityLoopContextReadPort",
    "QualityLoopContextWorkspacePort",
    "QualityLoopReleaseDecisionReadPort",
    "QualityLoopScopeWorkspacePort",
]
