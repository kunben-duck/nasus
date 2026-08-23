from __future__ import annotations

from collections.abc import Callable, MutableMapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from ...application.agent.agent_models import ConversationSession
from ...application.platform.project_models import ProjectCard, VersionSummary
from ...application.quality_loop.quality_models import (
    ApprovalDetail,
    AssetLane,
    ExecutionEvidence,
    FailureReport,
    QualityAssetPack,
    ReleaseReadiness,
    RunDetail,
    RunSummary,
    USItem,
)
from ...application.system_image.system_image_models import (
    KnowledgeObject,
    QualityProfile,
    RawAssetRecord,
    TaskContext,
)


class ProjectPersistencePort(Protocol):
    def upsert_project(self, project: ProjectCard) -> None: ...

    def replace_versions(
        self,
        project_id: str,
        versions: list[VersionSummary],
    ) -> None: ...

    def list_us_items(
        self,
        project_id: str,
        version_id: str | None = None,
    ) -> list[USItem]: ...

    def replace_us_items(
        self,
        project_id: str,
        version_id: str | None,
        items: list[USItem],
    ) -> None: ...

    def replace_asset_lanes(
        self,
        project_id: str,
        us_id: str,
        lanes: list[AssetLane],
    ) -> None: ...

    def replace_runs(
        self,
        project_id: str,
        runs: list[RunDetail],
    ) -> None: ...

    def replace_approvals(
        self,
        project_id: str,
        approvals: list[ApprovalDetail],
    ) -> None: ...

    def replace_knowledge_objects(
        self,
        project_id: str,
        objects: list[KnowledgeObject],
    ) -> None: ...

    def upsert_quality_asset_pack(
        self,
        pack: QualityAssetPack,
        sort_order: int = 0,
    ) -> None: ...

    def upsert_release_readiness(
        self,
        project_id: str,
        readiness: ReleaseReadiness,
    ) -> None: ...


class QualityLoopPersistencePort(Protocol):
    def replace_runs(
        self,
        project_id: str,
        runs: list[RunDetail],
    ) -> None: ...

    def replace_execution_evidence(
        self,
        project_id: str,
        evidence: list[ExecutionEvidence],
    ) -> None: ...

    def list_failure_reports(self, project_id: str) -> list[FailureReport]: ...

    def replace_failure_analysis(
        self,
        project_id: str,
        runs: list[RunDetail],
        reports: list[FailureReport],
    ) -> None: ...


class EnsureSystemImageStatePort(Protocol):
    def __call__(
        self,
        project_id: str,
        *,
        ready: bool,
    ) -> Any: ...


class GrantProjectCreatorPort(Protocol):
    def __call__(self, project_id: str) -> Any: ...


class GetOrCreateConversationPort(Protocol):
    def __call__(
        self,
        space_type: str,
        space_id: str,
        title: str,
    ) -> ConversationSession: ...


@dataclass(frozen=True)
class QualityLoopProjectionState:
    """Mutable quality-loop projections owned by the composition root."""

    projects: MutableMapping[str, ProjectCard]
    versions: MutableMapping[str, list[VersionSummary]]
    us_items: MutableMapping[str, list[USItem]]
    asset_lanes: MutableMapping[str, list[AssetLane]]
    quality_asset_packs: MutableMapping[str, QualityAssetPack]
    runs: MutableMapping[str, list[RunSummary]]
    run_details: MutableMapping[str, RunDetail]
    execution_evidence: MutableMapping[str, list[ExecutionEvidence]]
    failure_reports: MutableMapping[str, list[FailureReport]]
    approvals: MutableMapping[str, list[Any]]
    knowledge_objects: MutableMapping[str, list[KnowledgeObject]]
    release_readiness: MutableMapping[str, ReleaseReadiness]
    conversations: MutableMapping[str, ConversationSession]
    raw_assets: MutableMapping[str, list[RawAssetRecord]]
    task_contexts: MutableMapping[str, list[TaskContext]]
    quality_profiles: MutableMapping[str, list[QualityProfile]]


@dataclass(frozen=True)
class QualityLoopWorkspaceAdapters:
    """Explicit infrastructure dependencies for quality-loop workspaces."""

    project_repository: ProjectPersistencePort
    quality_loop_repository: QualityLoopPersistencePort
    mutation_guard: Callable[[], AbstractContextManager[None]]
    ensure_system_image_state: EnsureSystemImageStatePort
    grant_project_creator: GrantProjectCreatorPort
    get_or_create_conversation: GetOrCreateConversationPort


__all__ = [
    "EnsureSystemImageStatePort",
    "GetOrCreateConversationPort",
    "GrantProjectCreatorPort",
    "ProjectPersistencePort",
    "QualityLoopPersistencePort",
    "QualityLoopProjectionState",
    "QualityLoopWorkspaceAdapters",
]
