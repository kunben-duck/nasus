from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any, Protocol

from ...application.agent.agent_models import AgentMemoryItem
from ...application.platform.model_settings import StudioSettings
from ...application.platform.project_models import ProjectCard, VersionSummary
from ...application.quality_loop.quality_models import AssetLane, USItem
from ...application.system_image.system_image_models import (
    BaselineRecord,
    ContextObjectOverlay,
    ContextRelationship,
    EmbeddingRecord,
    KnowledgeObject,
    QualityMetricSnapshot,
    QualityProfile,
    RawAssetChunk,
    RawAssetRecord,
    RerankRecord,
    RetrievalRun,
    TaskContext,
)
from ...domain.platform.llm_call import LLMCallContext


class ProjectPersistencePort(Protocol):
    def upsert_project(self, project: ProjectCard) -> None: ...

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

    def replace_knowledge_objects(
        self,
        project_id: str,
        objects: list[KnowledgeObject],
    ) -> None: ...


class DurableProjectRepositoryPort(ProjectPersistencePort, Protocol):
    def get_project(self, project_id: str) -> ProjectCard | None: ...

    def list_versions(self, project_id: str) -> list[VersionSummary]: ...


class DurableQualityLoopRepositoryPort(Protocol):
    def list_us_items(
        self,
        project_id: str,
        version_id: str | None = None,
    ) -> list[USItem]: ...

    def list_asset_lanes(self, project_id: str) -> dict[str, list[AssetLane]]: ...

    def list_asset_lanes_for_us(self, us_id: str) -> list[AssetLane]: ...

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


class DurableSystemImageSnapshotPort(Protocol):
    knowledge_objects: list[KnowledgeObject]
    raw_assets: list[RawAssetRecord]
    raw_asset_chunks: list[RawAssetChunk]
    baselines: list[BaselineRecord]
    relationships: list[ContextRelationship]
    overlays: list[ContextObjectOverlay]
    metric_snapshots: list[QualityMetricSnapshot]
    embedding_records: list[EmbeddingRecord]
    retrieval_runs: list[RetrievalRun]
    rerank_records: list[RerankRecord]
    task_contexts: list[TaskContext]
    quality_profiles: list[QualityProfile]


class SystemImagePersistencePort(Protocol):
    def replace_system_image(self, project_id: str, **payload: Any) -> None: ...


class DurableSystemImageRepositoryPort(SystemImagePersistencePort, Protocol):
    def load_project_snapshot(
        self,
        project_id: str,
    ) -> DurableSystemImageSnapshotPort: ...

    def replace_knowledge_objects(
        self,
        project_id: str,
        objects: list[KnowledgeObject],
    ) -> None: ...
class ProjectReadModelRefreshPort(Protocol):
    def refresh_project(self, project_id: str) -> None: ...

    def refresh_system_image(self, project_id: str) -> None: ...


class ProjectAccessPort(Protocol):
    def require_project_access(self, project_id: str) -> Any: ...


class ObjectStoragePutResultPort(Protocol):
    storage_ref: str


class SystemImageObjectStoragePort(Protocol):
    def put_json(
        self,
        key: str,
        payload: dict[str, Any],
    ) -> ObjectStoragePutResultPort: ...

    def get_json(self, storage_ref: str) -> dict[str, Any]: ...


class SystemImageModelGatewayPort(Protocol):
    async def embed_texts(
        self,
        *,
        settings: StudioSettings,
        texts: list[str],
        custom_api_key: str,
        call_context: LLMCallContext | None = None,
    ) -> Any: ...

    async def rerank_candidates(
        self,
        *,
        settings: StudioSettings,
        query: str,
        documents: list[str],
        custom_api_key: str,
        call_context: LLMCallContext | None = None,
    ) -> Any: ...


@dataclass(frozen=True)
class SystemImageProjectionState:
    """Mutable compatibility projections owned by the application composition root."""

    projects: MutableMapping[str, ProjectCard]
    versions: MutableMapping[str, list[VersionSummary]]
    us_items: MutableMapping[str, list[USItem]]
    asset_lanes: MutableMapping[str, list[AssetLane]]
    knowledge_objects: MutableMapping[str, list[KnowledgeObject]]
    raw_assets: MutableMapping[str, list[RawAssetRecord]]
    raw_asset_chunks: MutableMapping[str, list[RawAssetChunk]]
    baselines: MutableMapping[str, list[BaselineRecord]]
    context_relationships: MutableMapping[str, list[ContextRelationship]]
    context_object_overlays: MutableMapping[str, list[ContextObjectOverlay]]
    quality_metric_snapshots: MutableMapping[str, list[QualityMetricSnapshot]]
    embedding_records: MutableMapping[str, list[EmbeddingRecord]]
    retrieval_runs: MutableMapping[str, list[RetrievalRun]]
    rerank_records: MutableMapping[str, list[RerankRecord]]
    task_contexts: MutableMapping[str, list[TaskContext]]
    quality_profiles: MutableMapping[str, list[QualityProfile]]


@dataclass(frozen=True)
class SystemImageRetrievalState:
    """Read projections required by the Agent-facing system-image retriever."""

    system_image: SystemImageProjectionState
    agent_memory_items: Mapping[str, AgentMemoryItem]


@dataclass(frozen=True)
class SystemImageWorkspaceAdapters:
    """Explicit infrastructure dependencies required by the system-image workspace."""

    project_repository: ProjectPersistencePort
    system_image_repository: SystemImagePersistencePort
    project_read_model_refresh: ProjectReadModelRefreshPort
    project_access: ProjectAccessPort
    object_storage: SystemImageObjectStoragePort
    model_gateway: SystemImageModelGatewayPort
    settings_provider: Callable[[], StudioSettings]
    custom_api_key_provider: Callable[[str], str]


@dataclass(frozen=True)
class DurableSystemImageWorkspaceAdapters:
    """Repository-backed dependencies for the production system-image workspace."""

    project_repository: DurableProjectRepositoryPort
    quality_loop_repository: DurableQualityLoopRepositoryPort
    system_image_repository: DurableSystemImageRepositoryPort
    project_read_model_refresh: ProjectReadModelRefreshPort
    project_access: ProjectAccessPort
    object_storage: SystemImageObjectStoragePort
    model_gateway: SystemImageModelGatewayPort
    settings_provider: Callable[[], StudioSettings]
    custom_api_key_provider: Callable[[str], str]


__all__ = [
    "DurableSystemImageWorkspaceAdapters",
    "SystemImageProjectionState",
    "SystemImageRetrievalState",
    "SystemImageWorkspaceAdapters",
]
