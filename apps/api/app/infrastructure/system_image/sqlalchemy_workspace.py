from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
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
from .workspace_dependencies import DurableSystemImageWorkspaceAdapters


@dataclass
class _ProjectWorkspaceSnapshot:
    project: ProjectCard
    versions: list[VersionSummary]
    us_items: list[USItem]
    asset_lanes: dict[str, list[AssetLane]]
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
    dirty: bool = False


class SQLAlchemySystemImageWorkspace:
    """Repository-backed production workspace for system-image use cases.

    A request-local snapshot preserves the application service's explicit
    `persist_system_image` commit boundary. PostgreSQL remains the source of
    truth; compatibility projections are refreshed only after a committed
    snapshot and are never read by this adapter.
    """

    def __init__(
        self,
        adapters: DurableSystemImageWorkspaceAdapters,
        *,
        require_live_model_routes: bool = False,
    ) -> None:
        self._adapters = adapters
        self._require_live_model_routes = require_live_model_routes
        self._request_snapshots: ContextVar[
            dict[str, _ProjectWorkspaceSnapshot] | None
        ] = ContextVar(
            f"nasus_system_image_workspace_{id(self)}",
            default=None,
        )

    def has_project(self, project_id: str) -> bool:
        return bool(project_id) and self._adapters.project_repository.get_project(project_id) is not None

    def get_project(self, project_id: str) -> ProjectCard:
        return self._snapshot(project_id).project

    def save_project(self, project: ProjectCard) -> None:
        snapshot = self._snapshot(project.id)
        snapshot.project = project
        self._adapters.project_repository.upsert_project(project)

    def list_versions(self, project_id: str) -> list[VersionSummary]:
        return self._snapshot(project_id).versions

    def list_us_items(self, project_id: str) -> list[USItem]:
        return self._snapshot(project_id).us_items

    def list_asset_lanes(self, us_id: str) -> list[AssetLane]:
        for snapshot in self._snapshots().values():
            if us_id in snapshot.asset_lanes or any(item.id == us_id for item in snapshot.us_items):
                return snapshot.asset_lanes.get(us_id, [])
        return self._adapters.quality_loop_repository.list_asset_lanes_for_us(us_id)

    def replace_us_items(
        self,
        project_id: str,
        version_id: str | None,
        items: list[USItem],
    ) -> None:
        snapshot = self._snapshot(project_id)
        snapshot.us_items = items
        self._adapters.quality_loop_repository.replace_us_items(
            project_id,
            version_id,
            items,
        )

    def replace_asset_lanes(
        self,
        project_id: str,
        us_id: str,
        lanes: list[AssetLane],
    ) -> None:
        snapshot = self._snapshot(project_id)
        snapshot.asset_lanes[us_id] = lanes
        self._adapters.quality_loop_repository.replace_asset_lanes(
            project_id,
            us_id,
            lanes,
        )

    def list_knowledge_objects(self, project_id: str) -> list[KnowledgeObject]:
        return self._snapshot(project_id).knowledge_objects

    def replace_knowledge_objects(
        self,
        project_id: str,
        objects: list[KnowledgeObject],
        *,
        persist_immediately: bool = False,
    ) -> None:
        snapshot = self._snapshot(project_id)
        snapshot.knowledge_objects = objects
        snapshot.dirty = True
        if persist_immediately:
            self._adapters.system_image_repository.replace_knowledge_objects(
                project_id,
                objects,
            )

    def list_raw_assets(self, project_id: str) -> list[RawAssetRecord]:
        return self._snapshot(project_id).raw_assets

    def replace_raw_assets(self, project_id: str, items: list[RawAssetRecord]) -> None:
        self._replace(project_id, "raw_assets", items)

    def list_raw_asset_chunks(self, project_id: str) -> list[RawAssetChunk]:
        return self._snapshot(project_id).raw_asset_chunks

    def replace_raw_asset_chunks(self, project_id: str, items: list[RawAssetChunk]) -> None:
        self._replace(project_id, "raw_asset_chunks", items)

    def list_baselines(self, project_id: str) -> list[BaselineRecord]:
        return self._snapshot(project_id).baselines

    def replace_baselines(self, project_id: str, items: list[BaselineRecord]) -> None:
        self._replace(project_id, "baselines", items)

    def list_context_relationships(self, project_id: str) -> list[ContextRelationship]:
        return self._snapshot(project_id).relationships

    def replace_context_relationships(
        self,
        project_id: str,
        items: list[ContextRelationship],
    ) -> None:
        self._replace(project_id, "relationships", items)

    def list_context_object_overlays(self, project_id: str) -> list[ContextObjectOverlay]:
        return self._snapshot(project_id).overlays

    def replace_context_object_overlays(
        self,
        project_id: str,
        items: list[ContextObjectOverlay],
    ) -> None:
        self._replace(project_id, "overlays", items)

    def list_quality_metric_snapshots(self, project_id: str) -> list[QualityMetricSnapshot]:
        return self._snapshot(project_id).metric_snapshots

    def replace_quality_metric_snapshots(
        self,
        project_id: str,
        items: list[QualityMetricSnapshot],
    ) -> None:
        self._replace(project_id, "metric_snapshots", items)

    def list_embedding_records(self, project_id: str) -> list[EmbeddingRecord]:
        return self._snapshot(project_id).embedding_records

    def replace_embedding_records(self, project_id: str, items: list[EmbeddingRecord]) -> None:
        self._replace(project_id, "embedding_records", items)

    def list_retrieval_runs(self, project_id: str) -> list[RetrievalRun]:
        return self._snapshot(project_id).retrieval_runs

    def replace_retrieval_runs(self, project_id: str, items: list[RetrievalRun]) -> None:
        self._replace(project_id, "retrieval_runs", items)

    def append_retrieval_run(self, project_id: str, item: RetrievalRun) -> None:
        snapshot = self._snapshot(project_id)
        snapshot.retrieval_runs.append(item)
        snapshot.dirty = True

    def list_rerank_records(self, project_id: str) -> list[RerankRecord]:
        return self._snapshot(project_id).rerank_records

    def replace_rerank_records(self, project_id: str, items: list[RerankRecord]) -> None:
        self._replace(project_id, "rerank_records", items)

    def list_task_contexts(self, project_id: str) -> list[TaskContext]:
        return self._snapshot(project_id).task_contexts

    def replace_task_contexts(self, project_id: str, items: list[TaskContext]) -> None:
        self._replace(project_id, "task_contexts", items)

    def list_quality_profiles(self, project_id: str) -> list[QualityProfile]:
        return self._snapshot(project_id).quality_profiles

    def replace_quality_profiles(self, project_id: str, items: list[QualityProfile]) -> None:
        self._replace(project_id, "quality_profiles", items)

    def persist_system_image(self, project_id: str) -> None:
        snapshot = self._snapshot(project_id)
        self._adapters.system_image_repository.replace_system_image(
            project_id,
            sources=snapshot.raw_assets,
            chunks=snapshot.raw_asset_chunks,
            baselines=snapshot.baselines,
            relationships=snapshot.relationships,
            overlays=snapshot.overlays,
            metric_snapshots=snapshot.metric_snapshots,
            embedding_records=snapshot.embedding_records,
            retrieval_runs=snapshot.retrieval_runs,
            rerank_records=snapshot.rerank_records,
            task_contexts=snapshot.task_contexts,
            quality_profiles=snapshot.quality_profiles,
            knowledge_objects=snapshot.knowledge_objects,
        )
        self._discard_snapshot(project_id)

    def refresh_project_read_model(self, project_id: str) -> None:
        current = self._snapshots().get(project_id)
        if current is None or not current.dirty:
            self._discard_snapshot(project_id)
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

    def _snapshot(self, project_id: str) -> _ProjectWorkspaceSnapshot:
        snapshots = self._snapshots()
        current = snapshots.get(project_id)
        if current is not None:
            return current

        project = self._adapters.project_repository.get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        system_image = self._adapters.system_image_repository.load_project_snapshot(project_id)
        current = _ProjectWorkspaceSnapshot(
            project=project,
            versions=self._adapters.project_repository.list_versions(project_id),
            us_items=self._adapters.quality_loop_repository.list_us_items(project_id),
            asset_lanes=self._adapters.quality_loop_repository.list_asset_lanes(project_id),
            knowledge_objects=system_image.knowledge_objects,
            raw_assets=system_image.raw_assets,
            raw_asset_chunks=system_image.raw_asset_chunks,
            baselines=system_image.baselines,
            relationships=system_image.relationships,
            overlays=system_image.overlays,
            metric_snapshots=system_image.metric_snapshots,
            embedding_records=system_image.embedding_records,
            retrieval_runs=system_image.retrieval_runs,
            rerank_records=system_image.rerank_records,
            task_contexts=system_image.task_contexts,
            quality_profiles=system_image.quality_profiles,
        )
        snapshots[project_id] = current
        return current

    def _replace(self, project_id: str, attribute: str, items: list[Any]) -> None:
        snapshot = self._snapshot(project_id)
        setattr(snapshot, attribute, items)
        snapshot.dirty = True

    def _snapshots(self) -> dict[str, _ProjectWorkspaceSnapshot]:
        snapshots = self._request_snapshots.get()
        if snapshots is None:
            snapshots = {}
            self._request_snapshots.set(snapshots)
        return snapshots

    def _discard_snapshot(self, project_id: str) -> None:
        snapshots = self._request_snapshots.get()
        if snapshots is not None:
            snapshots.pop(project_id, None)


__all__ = ["SQLAlchemySystemImageWorkspace"]
