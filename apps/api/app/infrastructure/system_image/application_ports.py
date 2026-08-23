from __future__ import annotations

from typing import Any, Sequence

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
from .model_route_policy import require_live_system_image_result
from .workspace_dependencies import (
    SystemImageProjectionState,
    SystemImageWorkspaceAdapters,
)


class LegacySystemImageWorkspace:
    """Translate the system-image application port to compatibility state.

    The composition root supplies the transitional projection and concrete
    infrastructure adapters. This boundary never discovers services through
    the compatibility facade.
    """

    def __init__(
        self,
        state: SystemImageProjectionState,
        adapters: SystemImageWorkspaceAdapters,
        *,
        require_live_model_routes: bool = False,
    ) -> None:
        self._state = state
        self._adapters = adapters
        self._require_live_model_routes = require_live_model_routes

    def has_project(self, project_id: str) -> bool:
        return bool(project_id) and project_id in self._state.projects

    def get_project(self, project_id: str) -> ProjectCard:
        return self._state.projects[project_id]

    def save_project(self, project: ProjectCard) -> None:
        self._state.projects[project.id] = project
        self._adapters.project_repository.upsert_project(project)

    def list_versions(self, project_id: str) -> list[VersionSummary]:
        return self._state.versions.get(project_id, [])

    def list_us_items(self, project_id: str) -> list[USItem]:
        return self._state.us_items.get(project_id, [])

    def list_asset_lanes(self, us_id: str) -> list[AssetLane]:
        return self._state.asset_lanes.get(us_id, [])

    def replace_us_items(
        self,
        project_id: str,
        version_id: str | None,
        items: list[USItem],
    ) -> None:
        self._state.us_items[project_id] = items
        self._adapters.project_repository.replace_us_items(project_id, version_id, items)

    def replace_asset_lanes(
        self,
        project_id: str,
        us_id: str,
        lanes: list[AssetLane],
    ) -> None:
        self._state.asset_lanes[us_id] = lanes
        self._adapters.project_repository.replace_asset_lanes(project_id, us_id, lanes)

    def list_knowledge_objects(self, project_id: str) -> list[KnowledgeObject]:
        return self._state.knowledge_objects.get(project_id, [])

    def replace_knowledge_objects(
        self,
        project_id: str,
        objects: list[KnowledgeObject],
        *,
        persist_immediately: bool = False,
    ) -> None:
        self._state.knowledge_objects[project_id] = objects
        if persist_immediately:
            self._adapters.project_repository.replace_knowledge_objects(project_id, objects)

    def list_raw_assets(self, project_id: str) -> list[RawAssetRecord]:
        return self._state.raw_assets.get(project_id, [])

    def replace_raw_assets(self, project_id: str, items: list[RawAssetRecord]) -> None:
        self._state.raw_assets[project_id] = items

    def list_raw_asset_chunks(self, project_id: str) -> list[RawAssetChunk]:
        return self._state.raw_asset_chunks.get(project_id, [])

    def replace_raw_asset_chunks(self, project_id: str, items: list[RawAssetChunk]) -> None:
        self._state.raw_asset_chunks[project_id] = items

    def list_baselines(self, project_id: str) -> list[BaselineRecord]:
        return self._state.baselines.get(project_id, [])

    def replace_baselines(self, project_id: str, items: list[BaselineRecord]) -> None:
        self._state.baselines[project_id] = items

    def list_context_relationships(self, project_id: str) -> list[ContextRelationship]:
        return self._state.context_relationships.get(project_id, [])

    def replace_context_relationships(
        self,
        project_id: str,
        items: list[ContextRelationship],
    ) -> None:
        self._state.context_relationships[project_id] = items

    def list_context_object_overlays(self, project_id: str) -> list[ContextObjectOverlay]:
        return self._state.context_object_overlays.get(project_id, [])

    def replace_context_object_overlays(
        self,
        project_id: str,
        items: list[ContextObjectOverlay],
    ) -> None:
        self._state.context_object_overlays[project_id] = items

    def list_quality_metric_snapshots(self, project_id: str) -> list[QualityMetricSnapshot]:
        return self._state.quality_metric_snapshots.get(project_id, [])

    def replace_quality_metric_snapshots(
        self,
        project_id: str,
        items: list[QualityMetricSnapshot],
    ) -> None:
        self._state.quality_metric_snapshots[project_id] = items

    def list_embedding_records(self, project_id: str) -> list[EmbeddingRecord]:
        return self._state.embedding_records.get(project_id, [])

    def replace_embedding_records(self, project_id: str, items: list[EmbeddingRecord]) -> None:
        self._state.embedding_records[project_id] = items

    def list_retrieval_runs(self, project_id: str) -> list[RetrievalRun]:
        return self._state.retrieval_runs.get(project_id, [])

    def replace_retrieval_runs(self, project_id: str, items: list[RetrievalRun]) -> None:
        self._state.retrieval_runs[project_id] = items

    def append_retrieval_run(self, project_id: str, item: RetrievalRun) -> None:
        self._state.retrieval_runs.setdefault(project_id, []).append(item)

    def list_rerank_records(self, project_id: str) -> list[RerankRecord]:
        return self._state.rerank_records.get(project_id, [])

    def replace_rerank_records(self, project_id: str, items: list[RerankRecord]) -> None:
        self._state.rerank_records[project_id] = items

    def list_task_contexts(self, project_id: str) -> list[TaskContext]:
        return self._state.task_contexts.get(project_id, [])

    def replace_task_contexts(self, project_id: str, items: list[TaskContext]) -> None:
        self._state.task_contexts[project_id] = items

    def list_quality_profiles(self, project_id: str) -> list[QualityProfile]:
        return self._state.quality_profiles.get(project_id, [])

    def replace_quality_profiles(self, project_id: str, items: list[QualityProfile]) -> None:
        self._state.quality_profiles[project_id] = items

    def persist_system_image(self, project_id: str) -> None:
        self._adapters.system_image_repository.replace_system_image(
            project_id,
            sources=self.list_raw_assets(project_id),
            chunks=self.list_raw_asset_chunks(project_id),
            baselines=self.list_baselines(project_id),
            relationships=self.list_context_relationships(project_id),
            overlays=self.list_context_object_overlays(project_id),
            metric_snapshots=self.list_quality_metric_snapshots(project_id),
            embedding_records=self.list_embedding_records(project_id),
            retrieval_runs=self.list_retrieval_runs(project_id),
            rerank_records=self.list_rerank_records(project_id),
            task_contexts=self.list_task_contexts(project_id),
            quality_profiles=self.list_quality_profiles(project_id),
        )

    def refresh_project_read_model(self, project_id: str) -> None:
        self._adapters.project_read_model_refresh.refresh_system_image(project_id)

    def require_project_access(self, project_id: str) -> None:
        self._adapters.project_access.require_project_access(project_id)

    def put_json(self, key: str, payload: dict[str, Any]) -> str:
        return self._adapters.object_storage.put_json(key, payload).storage_ref

    def get_json(self, storage_ref: str) -> dict[str, Any]:
        return self._adapters.object_storage.get_json(storage_ref)

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        call_context: LLMCallContext | None = None,
    ) -> Any:
        call_kwargs = {}
        if call_context is not None:
            call_kwargs["call_context"] = call_context
        result = await self._adapters.model_gateway.embed_texts(
            settings=self._adapters.settings_provider(),
            texts=list(texts),
            custom_api_key=self._adapters.custom_api_key_provider("embedding"),
            **call_kwargs,
        )
        if self._require_live_model_routes:
            require_live_system_image_result("embedding", result)
        return result

    async def rerank_candidates(
        self,
        *,
        query: str,
        candidates: Sequence[str],
        call_context: LLMCallContext | None = None,
    ) -> Any:
        call_kwargs = {}
        if call_context is not None:
            call_kwargs["call_context"] = call_context
        result = await self._adapters.model_gateway.rerank_candidates(
            settings=self._adapters.settings_provider(),
            query=query,
            documents=list(candidates),
            custom_api_key=self._adapters.custom_api_key_provider("rerank"),
            **call_kwargs,
        )
        if self._require_live_model_routes:
            require_live_system_image_result("rerank", result)
        return result


__all__ = ["LegacySystemImageWorkspace"]
