from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ...domain.system_image.build_state import resolve_build_state
from ...domain.system_image.materialization import require_materialized_evidence
from ...domain.system_image.source_binding import (
    REQUIRED_SOURCE_TYPES,
    default_source_uri,
    is_placeholder_source,
    missing_source_types,
    source_binding_incomplete,
)
from .context_extraction import ContextExtractionService
from .embedding_records import SystemImageEmbeddingRecordApplicationService
from .materialization_snapshot import SystemImageMaterializationSnapshot
from .persistence import SystemImagePersistenceApplicationService
from .ports import SystemImageWorkspacePort
from .quality_contexts import SystemImageQualityContextApplicationService
from .raw_asset_chunks import SystemImageRawAssetChunkApplicationService
from .retrieval_port import SystemImageRetrievalIndexPort
from .source_ingestion import SystemImageSourceIngestionApplicationService
from .source_ports import (
    CodeIntelligencePort,
    SourceIngestionPort,
    SourceSpec,
    SystemImageIngestionProjectionPort,
)
from .us_work_items import SystemImageUSWorkItemApplicationService
from .system_image_models import (
    BaselineRecord,
    RawAssetRecord,
    SystemImageBuildState,
    SystemImageResponse,
)

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SystemImageService:
    def __init__(
        self,
        workspace: SystemImageWorkspacePort,
        source_ingestion: SourceIngestionPort,
        retrieval_index: SystemImageRetrievalIndexPort,
        ingestion_projection: SystemImageIngestionProjectionPort,
        code_intelligence: CodeIntelligencePort,
    ) -> None:
        self.workspace = workspace
        self.source_ingestion = source_ingestion
        self.persistence = SystemImagePersistenceApplicationService(workspace)
        self.raw_asset_chunks = SystemImageRawAssetChunkApplicationService(workspace, self.source_ingestion)
        self.source_ingestion_use_cases = SystemImageSourceIngestionApplicationService(
            ingestion_projection,
            self.source_ingestion,
            self.raw_asset_chunks,
        )
        self.embedding_records = SystemImageEmbeddingRecordApplicationService(
            workspace,
            self.raw_asset_chunks,
        )
        self.quality_contexts = SystemImageQualityContextApplicationService(
            workspace,
            self.raw_asset_chunks,
            self.embedding_records,
            retrieval_index,
        )
        self.us_work_items = SystemImageUSWorkItemApplicationService(workspace)
        self.context_extraction = ContextExtractionService(
            self.source_ingestion,
            code_intelligence,
        )

    def ensure_state(self, project_id: str, *, ready: bool, version_id: Optional[str] = None) -> None:
        project = self.workspace.get_project(project_id)
        now = _now_iso()
        baseline_id = f"base_{project_id}_official"
        status = "ready" if ready else "draft"
        sources = self.workspace.list_raw_assets(project_id)
        objects = self.workspace.list_knowledge_objects(project_id)
        relationships = self.workspace.list_context_relationships(project_id)
        metrics = self.workspace.list_quality_metric_snapshots(project_id)

        if ready:
            require_materialized_evidence(
                objects=objects,
                relationships=relationships,
                metrics=metrics,
            )

        if not sources:
            self.workspace.replace_raw_assets(project_id, [
                RawAssetRecord(
                    id=f"raw_{project_id}_code",
                    project_id=project_id,
                    version_id=version_id,
                    source_type="code",
                    source_uri=self.default_source_uri(project_id, "code"),
                    ingestion_status="pending",
                    content_hash="",
                    content_ref=None,
                    evidence_refs=[],
                    last_ingested_at=None,
                ),
                RawAssetRecord(
                    id=f"raw_{project_id}_us",
                    project_id=project_id,
                    version_id=version_id,
                    source_type="us_doc",
                    source_uri=self.default_source_uri(project_id, "us_doc"),
                    ingestion_status="pending",
                    content_hash="",
                    content_ref=None,
                    evidence_refs=[],
                    last_ingested_at=None,
                ),
                RawAssetRecord(
                    id=f"raw_{project_id}_tests",
                    project_id=project_id,
                    version_id=version_id,
                    source_type="test_asset",
                    source_uri=self.default_source_uri(project_id, "test_asset"),
                    ingestion_status="pending",
                    content_hash="",
                    content_ref=None,
                    evidence_refs=[],
                    last_ingested_at=None,
                ),
            ])
        self.workspace.replace_baselines(project_id, [
            BaselineRecord(
                id=baseline_id,
                project_id=project_id,
                kind="official",
                status=status,
                fork_strategy="copy_on_write",
                object_count=len(objects),
                relationship_count=len(relationships) if ready else 0,
                metric_snapshot_count=len(metrics) if ready else 0,
                updated_at=now,
            )
        ])

        if not ready:
            self._clear_materialized_context(project_id)
        self.persistence.persist(project_id)

    def _clear_materialized_context(self, project_id: str) -> None:
        self.workspace.replace_raw_asset_chunks(project_id, [])
        self.workspace.replace_context_relationships(project_id, [])
        self.workspace.replace_context_object_overlays(project_id, [])
        self.workspace.replace_quality_metric_snapshots(project_id, [])
        self.workspace.replace_embedding_records(project_id, [])
        self.workspace.replace_retrieval_runs(project_id, [])
        self.workspace.replace_rerank_records(project_id, [])
        self.workspace.replace_task_contexts(project_id, [])
        self.workspace.replace_quality_profiles(project_id, [])

    def default_source_uri(self, project_id: str, source_type: str) -> str:
        project = self.workspace.get_project(project_id)
        return default_source_uri(project.name, source_type)

    def source_binding_incomplete(self, project_id: str) -> bool:
        project = self.workspace.get_project(project_id)
        return source_binding_incomplete(self.workspace.list_raw_assets(project_id), project.name)

    def missing_source_types(self, project_id: str) -> list[str]:
        project = self.workspace.get_project(project_id)
        return missing_source_types(self.workspace.list_raw_assets(project_id), project.name)

    def register_sources(
        self,
        project_id: str,
        source_specs: list[SourceSpec] | None = None,
        *,
        registered_by_actor: str = "system",
        registered_from_invocation_id: str | None = None,
    ) -> SystemImageResponse:
        self.source_ingestion_use_cases.register_sources(
            project_id,
            source_specs,
            registered_by_actor=registered_by_actor,
            registered_from_invocation_id=registered_from_invocation_id,
            ensure_draft_state=lambda: self.ensure_state(project_id, ready=False),
        )
        return self.get(project_id)

    def ingest_sources(self, project_id: str) -> SystemImageResponse:
        self.source_ingestion_use_cases.ingest_sources(
            project_id,
            ensure_draft_state=lambda: self.ensure_state(project_id, ready=False),
            source_binding_incomplete=lambda: self.source_binding_incomplete(project_id),
            missing_source_types=lambda: self.missing_source_types(project_id),
        )
        return self.get(project_id)

    async def materialize_context(self, project_id: str) -> SystemImageResponse:
        self.ingest_sources(project_id)
        self._ensure_sources_ready(project_id, stage="materialize system context")
        versions = self.workspace.list_versions(project_id)
        version_id = versions[0].id if versions else None
        snapshot = self._capture_materialization_snapshot(
            project_id,
            version_id=version_id,
        )
        try:
            return await self._materialize_context(
                project_id,
                version_id=version_id,
            )
        except Exception:
            self._restore_materialization_snapshot(project_id, snapshot)
            raise

    async def _materialize_context(
        self,
        project_id: str,
        *,
        version_id: str | None,
    ) -> SystemImageResponse:
        baselines = self.workspace.list_baselines(project_id)
        baseline_id = (
            baselines[0].id
            if baselines
            else f"base_{project_id}_official"
        )
        now = _now_iso()
        extracted = self.context_extraction.extract(
            project_id=project_id,
            project_name=self.workspace.get_project(project_id).name,
            baseline_id=baseline_id,
            sources=self.workspace.list_raw_assets(project_id),
            version_id=version_id,
            captured_at=now,
        )
        require_materialized_evidence(
            objects=extracted.objects,
            relationships=extracted.relationships,
            metrics=extracted.metrics,
        )
        self.workspace.replace_knowledge_objects(project_id, extracted.objects)
        self.workspace.replace_context_relationships(project_id, extracted.relationships)
        self.workspace.replace_quality_metric_snapshots(project_id, extracted.metrics)

        self.us_work_items.sync_from_context(project_id, version_id=version_id)
        await self.quality_contexts.materialize(
            project_id,
            baseline_id=baseline_id,
            version_id=version_id,
            captured_at=now,
        )

        baselines = self.workspace.list_baselines(project_id)
        if baselines:
            baselines[0].object_count = len(self.workspace.list_knowledge_objects(project_id))
            baselines[0].relationship_count = len(self.workspace.list_context_relationships(project_id))
            baselines[0].metric_snapshot_count = len(self.workspace.list_quality_metric_snapshots(project_id))
            baselines[0].updated_at = now
            self.workspace.replace_baselines(project_id, baselines)

        project = self.workspace.get_project(project_id)
        project.progress = max(project.progress, 24)
        self.workspace.save_project(project)
        self.workspace.replace_knowledge_objects(
            project_id,
            self.workspace.list_knowledge_objects(project_id),
            persist_immediately=True,
        )
        self.persistence.persist(project_id)
        self.workspace.refresh_project_read_model(project_id)
        return self.get(project_id)

    def _capture_materialization_snapshot(
        self,
        project_id: str,
        *,
        version_id: str | None,
    ) -> SystemImageMaterializationSnapshot:
        us_items = [
            item.model_copy(deep=True)
            for item in self.workspace.list_us_items(project_id)
        ]
        return SystemImageMaterializationSnapshot(
            project=self.workspace.get_project(project_id).model_copy(deep=True),
            version_id=version_id,
            chunks=self._copies(self.workspace.list_raw_asset_chunks(project_id)),
            objects=self._copies(self.workspace.list_knowledge_objects(project_id)),
            relationships=self._copies(self.workspace.list_context_relationships(project_id)),
            metrics=self._copies(self.workspace.list_quality_metric_snapshots(project_id)),
            baselines=self._copies(self.workspace.list_baselines(project_id)),
            embeddings=self._copies(self.workspace.list_embedding_records(project_id)),
            retrieval_runs=self._copies(self.workspace.list_retrieval_runs(project_id)),
            rerank_records=self._copies(self.workspace.list_rerank_records(project_id)),
            task_contexts=self._copies(self.workspace.list_task_contexts(project_id)),
            quality_profiles=self._copies(self.workspace.list_quality_profiles(project_id)),
            us_items=us_items,
            asset_lanes={
                item.id: self._copies(self.workspace.list_asset_lanes(item.id))
                for item in us_items
            },
        )

    def _restore_materialization_snapshot(
        self,
        project_id: str,
        snapshot: SystemImageMaterializationSnapshot,
    ) -> None:
        current_us_ids = {
            item.id
            for item in self.workspace.list_us_items(project_id)
        }
        self.workspace.replace_raw_asset_chunks(project_id, self._copies(snapshot.chunks))
        self.workspace.replace_knowledge_objects(
            project_id,
            self._copies(snapshot.objects),
            persist_immediately=True,
        )
        self.workspace.replace_context_relationships(
            project_id,
            self._copies(snapshot.relationships),
        )
        self.workspace.replace_quality_metric_snapshots(
            project_id,
            self._copies(snapshot.metrics),
        )
        self.workspace.replace_baselines(project_id, self._copies(snapshot.baselines))
        self.workspace.replace_embedding_records(project_id, self._copies(snapshot.embeddings))
        self.workspace.replace_retrieval_runs(project_id, self._copies(snapshot.retrieval_runs))
        self.workspace.replace_rerank_records(project_id, self._copies(snapshot.rerank_records))
        self.workspace.replace_task_contexts(project_id, self._copies(snapshot.task_contexts))
        self.workspace.replace_quality_profiles(project_id, self._copies(snapshot.quality_profiles))
        self.workspace.replace_us_items(
            project_id,
            snapshot.version_id,
            self._copies(snapshot.us_items),
        )
        for us_id in current_us_ids | set(snapshot.asset_lanes):
            self.workspace.replace_asset_lanes(
                project_id,
                us_id,
                self._copies(snapshot.asset_lanes.get(us_id, [])),
            )
        self.workspace.save_project(snapshot.project.model_copy(deep=True))
        self.persistence.persist(project_id)
        self.workspace.refresh_project_read_model(project_id)

    @staticmethod
    def _copies(items):
        return [item.model_copy(deep=True) for item in items]

    async def initialize_baseline(self, project_id: str) -> SystemImageResponse:
        await self.materialize_context(project_id)
        self._ensure_sources_ready(project_id, stage="initialize Official System Image")
        require_materialized_evidence(
            objects=self.workspace.list_knowledge_objects(project_id),
            relationships=self.workspace.list_context_relationships(project_id),
            metrics=self.workspace.list_quality_metric_snapshots(project_id),
        )
        project = self.workspace.get_project(project_id)
        project.system_image_status = "ready"
        project.progress = max(project.progress, 28)
        self.workspace.save_project(project)
        versions = self.workspace.list_versions(project_id)
        version_id = versions[0].id if versions else None
        self.ensure_state(project_id, ready=True, version_id=version_id)
        self.workspace.refresh_project_read_model(project_id)
        return self.get(project_id)

    def get(self, project_id: str) -> SystemImageResponse:
        self.workspace.refresh_project_read_model(project_id)
        project = self.workspace.get_project(project_id)
        baselines = self.workspace.list_baselines(project_id)
        baseline = baselines[0] if baselines else None
        build_state = self._build_state(project_id, baseline)
        source_counts = {
            source_type: sum(
                1
                for source in self.workspace.list_raw_assets(project_id)
                if source.source_type == source_type
            )
            for source_type in ["code", "us_doc", "test_asset"]
        }
        summary = (
            f"{project.name} system image is {project.system_image_status}; build state is {build_state.status}. "
            f"Sources: code={source_counts['code']}, us_doc={source_counts['us_doc']}, "
            f"test_asset={source_counts['test_asset']}. "
            f"Baseline {baseline.id if baseline else 'not initialized'} has "
            f"{baseline.object_count if baseline else 0} objects and "
            f"{baseline.relationship_count if baseline else 0} relationships."
        )
        return SystemImageResponse(
            project=project,
            summary=summary,
            build_state=build_state,
            baselines=baselines,
            sources=self.workspace.list_raw_assets(project_id),
            chunks=self.workspace.list_raw_asset_chunks(project_id),
            objects=self.workspace.list_knowledge_objects(project_id),
            relationships=self.workspace.list_context_relationships(project_id),
            overlays=self.workspace.list_context_object_overlays(project_id),
            metric_snapshots=self.workspace.list_quality_metric_snapshots(project_id),
            embedding_records=self.workspace.list_embedding_records(project_id),
            retrieval_runs=self.workspace.list_retrieval_runs(project_id),
            rerank_records=self.workspace.list_rerank_records(project_id),
            task_contexts=self.workspace.list_task_contexts(project_id),
            quality_profiles=self.workspace.list_quality_profiles(project_id),
        )

    def _build_state(self, project_id: str, baseline: BaselineRecord | None) -> SystemImageBuildState:
        project = self.workspace.get_project(project_id)
        sources = [
            source
            for source in self.workspace.list_raw_assets(project_id)
            if not is_placeholder_source(source, project.name)
        ]
        decision = resolve_build_state(
            sources=sources,
            missing_source_types=self.missing_source_types(project_id),
            has_context=bool(self.workspace.list_knowledge_objects(project_id))
            and bool(self.workspace.list_context_relationships(project_id)),
            has_metrics=bool(self.workspace.list_quality_metric_snapshots(project_id)),
            baseline_status=baseline.status if baseline else None,
            project_system_image_status=project.system_image_status,
        )
        return SystemImageBuildState(**decision.to_api_kwargs())

    def _ensure_sources_ready(self, project_id: str, *, stage: str) -> None:
        required_sources = [
            source
            for source in self.workspace.list_raw_assets(project_id)
            if source.source_type in REQUIRED_SOURCE_TYPES
        ]
        failed_required_sources = [
            source
            for source in required_sources
            if source.ingestion_status == "failed"
        ]
        if failed_required_sources:
            failed = ", ".join(
                f"{source.source_type}:{source.source_uri}"
                for source in failed_required_sources
            )
            raise RuntimeError(f"Cannot {stage}; source ingestion failed for {failed}.")
        unavailable_required_types = [
            required_type
            for required_type in REQUIRED_SOURCE_TYPES
            if not any(
                source.source_type == required_type and source.ingestion_status == "indexed"
                for source in required_sources
            )
        ]
        if unavailable_required_types:
            unavailable = ", ".join(unavailable_required_types)
            raise RuntimeError(
                f"Cannot {stage}; required source types are not indexed: {unavailable}."
            )
