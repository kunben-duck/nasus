from __future__ import annotations

from typing import Protocol

from ...application.agent.agent_models import ConversationSession
from ...application.quality_loop.ports import QualityLoopConversationScope
from ...application.quality_loop.quality_models import (
    AssetLane,
    ExecutionEvidence,
    FailureReport,
    QualityAssetPack,
    ReleaseReadiness,
    RunDetail,
    USItem,
)
from ...application.platform.project_models import ProjectCard, VersionSummary
from ...application.system_image.system_image_models import QualityProfile, TaskContext


class QualityLoopRunRepositoryPort(Protocol):
    """Entity-grained persistence required by run and failure workflows."""

    def get_us_item_for_project(self, project_id: str, us_id: str) -> USItem | None:
        ...

    def upsert_run_detail(self, project_id: str, run: RunDetail) -> None:
        ...

    def replace_execution_evidence_for_run(
        self,
        project_id: str,
        run_id: str,
        evidence: list[ExecutionEvidence],
    ) -> None:
        ...

    def list_failure_reports(self, project_id: str) -> list[FailureReport]:
        ...

    def upsert_failure_analysis(
        self,
        project_id: str,
        run: RunDetail,
        reports: list[FailureReport],
    ) -> None:
        ...


class QualityLoopScopeRepositoryPort(Protocol):
    def project_id_for_us(self, us_id: str) -> str | None:
        ...

    def first_us_id(self, project_id: str) -> str | None:
        ...

    def project_id_for_run(self, run_id: str) -> str | None:
        ...

    def list_run_details(self, project_id: str) -> list[RunDetail]:
        ...

    def us_id_for_run_evidence(self, project_id: str, run_id: str) -> str | None:
        ...


class QualityLoopContextRepositoryPort(Protocol):
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

    def list_asset_lanes_for_us(self, us_id: str) -> list[AssetLane]:
        ...


class SystemImageContextRepositoryPort(Protocol):
    def list_task_contexts(self, project_id: str) -> list[TaskContext]:
        ...

    def list_quality_profiles(self, project_id: str) -> list[QualityProfile]:
        ...


class QualityAssetProgressRepositoryPort(Protocol):
    def list_asset_lanes_for_us(self, us_id: str) -> list[AssetLane]:
        ...

    def ensure_asset_lanes(
        self,
        project_id: str,
        us_id: str,
        lanes: list[AssetLane],
    ) -> None:
        ...

    def upsert_asset_lane(
        self,
        project_id: str,
        us_id: str,
        lane: AssetLane,
    ) -> None:
        ...

    def get_us_item_for_project(self, project_id: str, us_id: str) -> USItem | None:
        ...

    def upsert_us_item_preserving_version(
        self,
        project_id: str,
        item: USItem,
    ) -> None:
        ...


class QualityAssetPackRepositoryPort(Protocol):
    def get_quality_asset_pack(
        self,
        project_id: str,
        us_id: str,
    ) -> QualityAssetPack | None:
        ...

    def upsert_quality_asset_pack(self, pack: QualityAssetPack) -> None:
        ...


class ProjectVersionRepositoryPort(Protocol):
    def get_project(self, project_id: str) -> ProjectCard | None:
        ...

    def upsert_project(self, project: ProjectCard) -> None:
        ...

    def list_versions(self, project_id: str) -> list[VersionSummary]:
        ...

    def prepend_version(self, project_id: str, version: VersionSummary) -> None:
        ...

    def save_version(self, project_id: str, version: VersionSummary) -> None:
        ...


class ProjectVersionQualityRepositoryPort(Protocol):
    def list_us_items(
        self,
        project_id: str,
        version_id: str | None = None,
    ) -> list[USItem]:
        ...

    def upsert_us_items(
        self,
        project_id: str,
        version_id: str | None,
        items: list[USItem],
    ) -> None:
        ...

    def upsert_us_item(
        self,
        project_id: str,
        version_id: str | None,
        item: USItem,
    ) -> None:
        ...

    def upsert_release_readiness(
        self,
        project_id: str,
        readiness: ReleaseReadiness,
    ) -> None:
        ...


class SystemImageEvidenceRepositoryPort(Protocol):
    def has_raw_assets(self, project_id: str) -> bool:
        ...


class EnsureSystemImageStatePort(Protocol):
    def __call__(self, project_id: str, *, ready: bool) -> object:
        ...


class GrantProjectCreatorPort(Protocol):
    def __call__(self, project_id: str) -> object:
        ...


class GetOrCreateProjectConversationPort(Protocol):
    def __call__(
        self,
        space_type: str,
        space_id: str,
        title: str,
    ) -> ConversationSession:
        ...


class ConversationScopeRepositoryPort(Protocol):
    def get_conversation(self, conversation_id: str) -> ConversationSession | None:
        ...


class SQLAlchemyQualityRunWorkspace:
    """Durable runner workspace without process-local projection coupling."""

    def __init__(self, repository: QualityLoopRunRepositoryPort) -> None:
        self._repository = repository

    def us_title(self, project_id: str, us_id: str) -> str | None:
        item = self._repository.get_us_item_for_project(project_id, us_id)
        return item.title if item is not None else None

    def save_run_detail(self, project_id: str, run: RunDetail) -> None:
        self._repository.upsert_run_detail(project_id, run.model_copy(deep=True))

    def replace_run_evidence(
        self,
        project_id: str,
        run_id: str,
        evidence: list[ExecutionEvidence],
    ) -> None:
        self._repository.replace_execution_evidence_for_run(
            project_id,
            run_id,
            [item.model_copy(deep=True) for item in evidence],
        )


class SQLAlchemyQualityFailureWorkspace:
    """Transactional failed-run and FailureReport persistence boundary."""

    def __init__(self, repository: QualityLoopRunRepositoryPort) -> None:
        self._repository = repository

    def list_failure_reports(self, project_id: str) -> list[FailureReport]:
        return [
            item.model_copy(deep=True)
            for item in self._repository.list_failure_reports(project_id)
        ]

    def save_failure_analysis(
        self,
        project_id: str,
        run: RunDetail,
        reports: list[FailureReport],
    ) -> None:
        self._repository.upsert_failure_analysis(
            project_id,
            run.model_copy(deep=True),
            [item.model_copy(deep=True) for item in reports],
        )


class SQLAlchemyQualityLoopContextWorkspace:
    """Read current quality context from canonical durable repositories."""

    def __init__(
        self,
        system_image: SystemImageContextRepositoryPort,
        quality_loop: QualityLoopContextRepositoryPort,
    ) -> None:
        self._system_image = system_image
        self._quality_loop = quality_loop

    def list_task_contexts(self, project_id: str) -> list[TaskContext]:
        return [
            item.model_copy(deep=True)
            for item in self._system_image.list_task_contexts(project_id)
        ]

    def list_quality_profiles(self, project_id: str) -> list[QualityProfile]:
        return [
            item.model_copy(deep=True)
            for item in self._system_image.list_quality_profiles(project_id)
        ]

    def get_quality_asset_pack(
        self,
        project_id: str,
        us_id: str,
    ) -> QualityAssetPack | None:
        pack = self._quality_loop.get_quality_asset_pack(project_id, us_id)
        return pack.model_copy(deep=True) if pack is not None else None

    def list_quality_asset_packs(self, project_id: str) -> list[QualityAssetPack]:
        return [
            item.model_copy(deep=True)
            for item in self._quality_loop.list_quality_asset_packs(project_id)
        ]

    def list_us_items(self, project_id: str) -> list[USItem]:
        return [
            item.model_copy(deep=True)
            for item in self._quality_loop.list_us_items(project_id)
        ]

    def project_id_for_us(self, us_id: str) -> str | None:
        return self._quality_loop.project_id_for_us(us_id)

    def list_asset_lanes(self, us_id: str) -> list[AssetLane]:
        return [
            item.model_copy(deep=True)
            for item in self._quality_loop.list_asset_lanes_for_us(us_id)
        ]


class SQLAlchemyQualityAssetProgressWorkspace:
    """Entity-grained lane and US progress persistence."""

    def __init__(self, repository: QualityAssetProgressRepositoryPort) -> None:
        self._repository = repository

    def list_asset_lanes(self, us_id: str) -> list[AssetLane]:
        return [
            item.model_copy(deep=True)
            for item in self._repository.list_asset_lanes_for_us(us_id)
        ]

    def ensure_asset_lanes(
        self,
        project_id: str,
        us_id: str,
        lanes: list[AssetLane],
    ) -> None:
        self._repository.ensure_asset_lanes(
            project_id,
            us_id,
            [item.model_copy(deep=True) for item in lanes],
        )

    def save_asset_lane(
        self,
        project_id: str,
        us_id: str,
        lane: AssetLane,
    ) -> None:
        self._repository.upsert_asset_lane(
            project_id,
            us_id,
            lane.model_copy(deep=True),
        )

    def get_us_item(self, project_id: str, us_id: str) -> USItem | None:
        item = self._repository.get_us_item_for_project(project_id, us_id)
        return item.model_copy(deep=True) if item is not None else None

    def save_us_item(self, project_id: str, item: USItem) -> None:
        self._repository.upsert_us_item_preserving_version(
            project_id,
            item.model_copy(deep=True),
        )


class SQLAlchemyQualityAssetPackWorkspace:
    """Durable QualityAssetPack aggregate persistence."""

    def __init__(self, repository: QualityAssetPackRepositoryPort) -> None:
        self._repository = repository

    def get_quality_asset_pack(
        self,
        project_id: str,
        us_id: str,
    ) -> QualityAssetPack | None:
        pack = self._repository.get_quality_asset_pack(project_id, us_id)
        return pack.model_copy(deep=True) if pack is not None else None

    def save_quality_asset_pack(self, pack: QualityAssetPack) -> None:
        self._repository.upsert_quality_asset_pack(pack.model_copy(deep=True))


class SQLAlchemyProjectVersionWorkspace:
    """Durable project/version onboarding workspace with entity-grained writes."""

    def __init__(
        self,
        projects: ProjectVersionRepositoryPort,
        quality_loop: ProjectVersionQualityRepositoryPort,
        system_image: SystemImageEvidenceRepositoryPort,
        conversations: ConversationScopeRepositoryPort,
        ensure_system_image_state: EnsureSystemImageStatePort,
        grant_project_creator: GrantProjectCreatorPort,
        get_or_create_conversation: GetOrCreateProjectConversationPort,
    ) -> None:
        self._projects = projects
        self._quality_loop = quality_loop
        self._system_image = system_image
        self._conversations = conversations
        self._ensure_system_image_state = ensure_system_image_state
        self._grant_project_creator = grant_project_creator
        self._get_or_create_conversation = get_or_create_conversation

    def initialize_project(self, project: ProjectCard) -> None:
        self._projects.upsert_project(project.model_copy(deep=True))
        self._ensure_system_image_state(project.id, ready=False)
        self._grant_project_creator(project.id)
        self._get_or_create_conversation("project", project.id, project.name)

    def has_project(self, project_id: str) -> bool:
        return bool(project_id) and self._projects.get_project(project_id) is not None

    def get_project(self, project_id: str) -> ProjectCard:
        project = self._projects.get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        return project.model_copy(deep=True)

    def save_project(self, project: ProjectCard) -> None:
        self._projects.upsert_project(project.model_copy(deep=True))

    def list_versions(self, project_id: str) -> list[VersionSummary]:
        return [
            item.model_copy(deep=True)
            for item in self._projects.list_versions(project_id)
        ]

    def prepend_version(
        self,
        project_id: str,
        version: VersionSummary,
    ) -> None:
        self._projects.prepend_version(project_id, version.model_copy(deep=True))

    def save_version(
        self,
        project_id: str,
        version: VersionSummary,
    ) -> None:
        self._projects.save_version(project_id, version.model_copy(deep=True))

    def list_us_items(
        self,
        project_id: str,
        version_id: str | None = None,
    ) -> list[USItem]:
        return [
            item.model_copy(deep=True)
            for item in self._quality_loop.list_us_items(project_id, version_id)
        ]

    def save_us_items(
        self,
        project_id: str,
        version_id: str | None,
        items: list[USItem],
    ) -> None:
        self._quality_loop.upsert_us_items(
            project_id,
            version_id,
            [item.model_copy(deep=True) for item in items],
        )

    def save_us_item(
        self,
        project_id: str,
        version_id: str | None,
        item: USItem,
    ) -> None:
        self._quality_loop.upsert_us_item(
            project_id,
            version_id,
            item.model_copy(deep=True),
        )

    def save_release_readiness(
        self,
        project_id: str,
        readiness: ReleaseReadiness,
    ) -> None:
        self._quality_loop.upsert_release_readiness(
            project_id,
            readiness.model_copy(deep=True),
        )

    def conversation_project_id(self, conversation_id: str | None) -> str | None:
        if not conversation_id:
            return None
        conversation = self._conversations.get_conversation(conversation_id)
        if conversation is None:
            return None
        if conversation.project_id:
            return conversation.project_id
        if conversation.space_type == "project":
            return conversation.space_id
        return None

    def has_indexed_system_image_evidence(self, project_id: str) -> bool:
        project = self._projects.get_project(project_id)
        return bool(
            project
            and project.system_image_status in {"indexed", "ready"}
            and self._system_image.has_raw_assets(project_id)
        )


class SQLAlchemyQualityLoopScopeWorkspace:
    """Resolve tool ownership from durable conversation and quality facts."""

    def __init__(
        self,
        quality_loop: QualityLoopScopeRepositoryPort,
        conversations: ConversationScopeRepositoryPort,
    ) -> None:
        self._quality_loop = quality_loop
        self._conversations = conversations

    def conversation_scope(
        self,
        conversation_id: str | None,
    ) -> QualityLoopConversationScope | None:
        if not conversation_id:
            return None
        conversation = self._conversations.get_conversation(conversation_id)
        if conversation is None:
            return None
        return QualityLoopConversationScope(
            project_id=conversation.project_id,
            us_id=conversation.us_id,
            space_type=conversation.space_type,
            space_id=conversation.space_id,
        )

    def project_id_for_us(self, us_id: str) -> str | None:
        return self._quality_loop.project_id_for_us(us_id)

    def first_us_id(self, project_id: str) -> str | None:
        return self._quality_loop.first_us_id(project_id)

    def project_id_for_run(self, run_id: str) -> str | None:
        return self._quality_loop.project_id_for_run(run_id)

    def list_run_details(self, project_id: str) -> list[RunDetail]:
        return [
            run.model_copy(deep=True)
            for run in self._quality_loop.list_run_details(project_id)
        ]

    def us_id_for_run_evidence(
        self,
        project_id: str,
        run_id: str,
    ) -> str | None:
        return self._quality_loop.us_id_for_run_evidence(project_id, run_id)


__all__ = [
    "SQLAlchemyProjectVersionWorkspace",
    "SQLAlchemyQualityAssetPackWorkspace",
    "SQLAlchemyQualityAssetProgressWorkspace",
    "SQLAlchemyQualityFailureWorkspace",
    "SQLAlchemyQualityLoopContextWorkspace",
    "SQLAlchemyQualityLoopScopeWorkspace",
    "SQLAlchemyQualityRunWorkspace",
]
