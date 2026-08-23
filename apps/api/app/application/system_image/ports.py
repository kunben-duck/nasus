from __future__ import annotations

from typing import Any, Protocol, Sequence

from ...domain.platform.llm_call import LLMCallContext
from ..platform.project_models import ProjectCard, VersionSummary
from ..quality_loop.quality_models import AssetLane, USItem
from .system_image_models import (
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


class SystemImageWorkspacePort(Protocol):
    """Application-facing boundary for system-image state and providers.

    The compatibility implementation may still project durable records into
    process memory, but system-image use cases only depend on this contract.
    Provider clients, repositories, and the global application facade stay
    behind the infrastructure adapter.
    """

    def has_project(self, project_id: str) -> bool: ...

    def get_project(self, project_id: str) -> ProjectCard: ...

    def save_project(self, project: ProjectCard) -> None: ...

    def list_versions(self, project_id: str) -> list[VersionSummary]: ...

    def list_us_items(self, project_id: str) -> list[USItem]: ...

    def list_asset_lanes(self, us_id: str) -> list[AssetLane]: ...

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

    def list_knowledge_objects(self, project_id: str) -> list[KnowledgeObject]: ...

    def replace_knowledge_objects(
        self,
        project_id: str,
        objects: list[KnowledgeObject],
        *,
        persist_immediately: bool = False,
    ) -> None: ...

    def list_raw_assets(self, project_id: str) -> list[RawAssetRecord]: ...

    def replace_raw_assets(self, project_id: str, items: list[RawAssetRecord]) -> None: ...

    def list_raw_asset_chunks(self, project_id: str) -> list[RawAssetChunk]: ...

    def replace_raw_asset_chunks(self, project_id: str, items: list[RawAssetChunk]) -> None: ...

    def list_baselines(self, project_id: str) -> list[BaselineRecord]: ...

    def replace_baselines(self, project_id: str, items: list[BaselineRecord]) -> None: ...

    def list_context_relationships(self, project_id: str) -> list[ContextRelationship]: ...

    def replace_context_relationships(
        self,
        project_id: str,
        items: list[ContextRelationship],
    ) -> None: ...

    def list_context_object_overlays(self, project_id: str) -> list[ContextObjectOverlay]: ...

    def replace_context_object_overlays(
        self,
        project_id: str,
        items: list[ContextObjectOverlay],
    ) -> None: ...

    def list_quality_metric_snapshots(self, project_id: str) -> list[QualityMetricSnapshot]: ...

    def replace_quality_metric_snapshots(
        self,
        project_id: str,
        items: list[QualityMetricSnapshot],
    ) -> None: ...

    def list_embedding_records(self, project_id: str) -> list[EmbeddingRecord]: ...

    def replace_embedding_records(self, project_id: str, items: list[EmbeddingRecord]) -> None: ...

    def list_retrieval_runs(self, project_id: str) -> list[RetrievalRun]: ...

    def replace_retrieval_runs(self, project_id: str, items: list[RetrievalRun]) -> None: ...

    def append_retrieval_run(self, project_id: str, item: RetrievalRun) -> None: ...

    def list_rerank_records(self, project_id: str) -> list[RerankRecord]: ...

    def replace_rerank_records(self, project_id: str, items: list[RerankRecord]) -> None: ...

    def list_task_contexts(self, project_id: str) -> list[TaskContext]: ...

    def replace_task_contexts(self, project_id: str, items: list[TaskContext]) -> None: ...

    def list_quality_profiles(self, project_id: str) -> list[QualityProfile]: ...

    def replace_quality_profiles(self, project_id: str, items: list[QualityProfile]) -> None: ...

    def persist_system_image(self, project_id: str) -> None: ...

    def refresh_project_read_model(self, project_id: str) -> None: ...

    def require_project_access(self, project_id: str) -> None: ...

    def put_json(self, key: str, payload: dict[str, Any]) -> str: ...

    def get_json(self, storage_ref: str) -> dict[str, Any]: ...

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        call_context: LLMCallContext | None = None,
    ) -> Any: ...

    async def rerank_candidates(
        self,
        *,
        query: str,
        candidates: Sequence[str],
        call_context: LLMCallContext | None = None,
    ) -> Any: ...


class SystemImageOperationsPort(Protocol):
    source_ingestion: Any

    def source_binding_incomplete(self, project_id: str) -> bool: ...

    def missing_source_types(self, project_id: str) -> list[str]: ...

    def register_sources(
        self,
        project_id: str,
        source_specs: Any = None,
        *,
        registered_by_actor: str = "system",
        registered_from_invocation_id: str | None = None,
    ) -> Any: ...

    def ingest_sources(self, project_id: str) -> Any: ...

    async def materialize_context(self, project_id: str) -> Any: ...

    async def initialize_baseline(self, project_id: str) -> Any: ...

    def get(self, project_id: str) -> Any: ...


__all__ = ["SystemImageOperationsPort", "SystemImageWorkspacePort"]
