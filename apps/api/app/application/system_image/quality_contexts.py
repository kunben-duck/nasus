from __future__ import annotations

from ...domain.system_image.quality_context import (
    automation_feasibility,
    context_confidence,
    context_hash,
    coverage_score,
    missing_quality_context,
    release_score,
    risk_drivers,
    risk_score,
)
from ...domain.platform.llm_call import LLMCallContext
from ..quality_loop.quality_models import USItem
from .embedding_records import SystemImageEmbeddingRecordApplicationService
from .ports import SystemImageWorkspacePort
from .raw_asset_chunks import SystemImageRawAssetChunkApplicationService
from .retrieval_port import HybridRetrievalQuery, SystemImageRetrievalIndexPort
from .system_image_models import (
    ContextRelationship,
    KnowledgeObject,
    QualityMetricSnapshot,
    QualityProfile,
    RawAssetChunk,
    RawAssetRecord,
    RerankRecord,
    RetrievalRun,
    TaskContext,
)


class SystemImageQualityContextApplicationService:
    """Materializes retrieval, rerank, task-context, and quality-profile read models."""

    def __init__(
        self,
        workspace: SystemImageWorkspacePort,
        raw_asset_chunks: SystemImageRawAssetChunkApplicationService,
        embedding_records: SystemImageEmbeddingRecordApplicationService,
        retrieval_index: SystemImageRetrievalIndexPort,
    ) -> None:
        self._workspace = workspace
        self._raw_asset_chunks = raw_asset_chunks
        self._embedding_records = embedding_records
        self._retrieval_index = retrieval_index

    async def materialize(
        self,
        project_id: str,
        *,
        baseline_id: str,
        version_id: str | None,
        captured_at: str,
    ) -> None:
        sources = self._workspace.list_raw_assets(project_id)
        if sources and not self._workspace.list_raw_asset_chunks(project_id):
            self._raw_asset_chunks.materialize(project_id, captured_at=captured_at)
        chunks = self._workspace.list_raw_asset_chunks(project_id)
        objects = self._workspace.list_knowledge_objects(project_id)
        relationships = self._workspace.list_context_relationships(project_id)
        metrics = self._workspace.list_quality_metric_snapshots(project_id)
        if not sources or not objects or not relationships or not metrics:
            self._retrieval_index.replace_embeddings(project_id, [])
            self._workspace.replace_embedding_records(project_id, [])
            self._workspace.replace_retrieval_runs(project_id, [])
            self._workspace.replace_rerank_records(project_id, [])
            self._workspace.replace_task_contexts(project_id, [])
            self._workspace.replace_quality_profiles(project_id, [])
            return

        us_items = self._workspace.list_us_items(project_id)
        context_targets = us_items or [
            USItem(
                id="project_context",
                title=f"{self._workspace.get_project(project_id).name} project context",
                owner="Nasus Agent",
                status="analysis",
                risk="medium",
                progress=0,
                next_action="Import US work items",
            )
        ]

        source_refs = [source.id for source in sources if source.ingestion_status == "indexed"]
        embedding_records = await self._embedding_records.materialize(
            project_id,
            baseline_id=baseline_id,
            sources=sources,
            chunks=chunks,
            objects=objects,
            captured_at=captured_at,
        )
        self._workspace.replace_embedding_records(project_id, embedding_records)
        self._retrieval_index.replace_embeddings(project_id, embedding_records)
        embedding_status = "ready" if embedding_records and all(item.status == "ready" for item in embedding_records) else "fallback"

        active_targets = context_targets[:8]
        retrieval_queries = [f"Build quality context for {target.title}" for target in active_targets]
        query_embeddings = await self._workspace.embed_texts(
            retrieval_queries,
            call_context=LLMCallContext(
                purpose="system_image.context_query_embedding",
                project_id=project_id,
                version_id=version_id,
            ),
        )

        retrieval_runs: list[RetrievalRun] = []
        rerank_records: list[RerankRecord] = []
        task_contexts: list[TaskContext] = []
        quality_profiles: list[QualityProfile] = []
        for target_index, target in enumerate(active_targets):
            target_us_id = None if target.id == "project_context" else target.id
            retrieval_id = f"retrieval_{project_id}_{target.id}"
            rerank_id = f"rerank_{project_id}_{target.id}"
            query = retrieval_queries[target_index]
            query_vector = query_embeddings.vectors[target_index] if target_index < len(query_embeddings.vectors) else []
            hits = self._retrieval_index.search(
                HybridRetrievalQuery(
                    project_id=project_id,
                    baseline_id=baseline_id,
                    query_text=query,
                    query_vector=tuple(query_vector),
                    embedding_model=query_embeddings.model_name,
                    embedding_version=embedding_records[0].embedding_version if embedding_records else "settings.current",
                    dimensions=len(query_vector) or query_embeddings.dimensions,
                    allow_fallback_vectors=query_embeddings.mode != "live" or embedding_status != "ready",
                )
            )
            result_refs = [hit.subject_ref for hit in hits]
            candidate_text_by_ref = {hit.subject_ref: hit.search_text for hit in hits}
            if not result_refs:
                result_refs = self._fallback_result_refs(chunks, objects, relationships, metrics)
            embedding_record_ids = [hit.embedding_record_id for hit in hits]
            rerank_result = await self._workspace.rerank_candidates(
                query=query,
                candidates=[
                    candidate_text_by_ref.get(ref)
                    or self.candidate_text(ref, sources, chunks, objects, relationships, metrics)
                    for ref in result_refs
                ],
                call_context=LLMCallContext(
                    purpose="system_image.context_rerank",
                    project_id=project_id,
                    version_id=version_id,
                    task_id=target_us_id,
                ),
            )
            ranked_refs = [result_refs[index] for index in rerank_result.ranked_indices if index < len(result_refs)]
            selected_refs = ranked_refs or result_refs
            context_projection = self._context_projection(
                selected_refs,
                sources=sources,
                chunks=chunks,
                objects=objects,
                relationships=relationships,
                metrics=metrics,
            )
            fallback_used = (
                embedding_status != "ready"
                or query_embeddings.mode != "live"
                or not hits
                or rerank_result.mode != "live"
            )
            retrieval_runs.append(
                RetrievalRun(
                    id=retrieval_id,
                    project_id=project_id,
                    baseline_id=baseline_id,
                    version_id=version_id,
                    us_id=target_us_id,
                    query=query,
                    strategy="rule_based_fusion" if fallback_used else "hybrid_graph_vector",
                    candidate_count=len(result_refs),
                    result_refs=selected_refs,
                    embedding_record_ids=embedding_record_ids,
                    rerank_record_id=rerank_id,
                    fallback_used=fallback_used,
                    created_at=captured_at,
                )
            )
            rerank_records.append(
                RerankRecord(
                    id=rerank_id,
                    project_id=project_id,
                    retrieval_run_id=retrieval_id,
                    rerank_model=rerank_result.model_name,
                    rerank_version="settings.current",
                    input_count=len(result_refs),
                    output_count=len(ranked_refs or result_refs),
                    status="completed" if rerank_result.mode == "live" else "fallback",
                    latency_ms=rerank_result.latency_ms,
                    fallback_reason=None if rerank_result.mode == "live" else rerank_result.reason,
                    created_at=captured_at,
                )
            )
            missing_context = missing_quality_context(sources, target_us_id)
            context_hash_value = context_hash(
                project_id,
                baseline_id,
                target.id,
                context_projection["source_refs"],
                context_projection["chunk_refs"],
                context_projection["object_refs"],
                context_projection["relationship_refs"],
                context_projection["metric_refs"],
            )
            task_context_id = f"taskctx_{project_id}_{target.id}"
            task_contexts.append(
                TaskContext(
                    id=task_context_id,
                    project_id=project_id,
                    baseline_id=baseline_id,
                    version_id=version_id,
                    us_id=target_us_id,
                    retrieval_run_id=retrieval_id,
                    summary=(
                        f"{target.title} is grounded by {len(source_refs)} indexed source groups, "
                        f"{len(context_projection['chunk_refs'])} retrieved raw asset chunks, "
                        f"{len(context_projection['object_refs'])} context objects, "
                        f"{len(context_projection['relationship_refs'])} relationships, "
                        f"and {len(context_projection['metric_refs'])} quality metrics."
                    ),
                    readiness="ready" if not missing_context else "blocked",
                    source_refs=context_projection["source_refs"],
                    object_refs=context_projection["object_refs"],
                    relationship_refs=context_projection["relationship_refs"],
                    metric_refs=context_projection["metric_refs"],
                    evidence_refs=context_projection["evidence_refs"],
                    missing_context=missing_context,
                    confidence=context_confidence(sources, relationships, metrics),
                    freshness_at=captured_at,
                    context_hash=context_hash_value,
                )
            )
            quality_profiles.append(
                QualityProfile(
                    id=f"quality_profile_{project_id}_{target.id}",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    version_id=version_id,
                    us_id=target_us_id,
                    task_context_id=task_context_id,
                    risk_score=risk_score(metrics),
                    coverage_score=coverage_score(metrics),
                    release_score=release_score(
                        metrics,
                        blocked_items=self._workspace.get_project(project_id).blocked_items,
                        pending_approvals=self._workspace.get_project(project_id).pending_approvals,
                    ),
                    automation_feasibility=automation_feasibility(metrics),
                    risk_drivers=risk_drivers(metrics, relationships),
                    regression_scope_refs=[
                        item.id
                        for item in objects
                        if item.id in context_projection["object_refs"]
                        and item.type in {"CodeFunction", "CodeClass", "CodeModule", "Feature"}
                    ][:12],
                    evidence_refs=context_projection["evidence_refs"],
                    confidence=context_confidence(sources, relationships, metrics),
                    freshness_at=captured_at,
                )
            )

        self._workspace.replace_embedding_records(project_id, embedding_records)
        self._workspace.replace_retrieval_runs(project_id, retrieval_runs)
        self._workspace.replace_rerank_records(project_id, rerank_records)
        self._workspace.replace_task_contexts(project_id, task_contexts)
        self._workspace.replace_quality_profiles(project_id, quality_profiles)

    @staticmethod
    def _fallback_result_refs(
        chunks: list[RawAssetChunk],
        objects: list[KnowledgeObject],
        relationships: list[ContextRelationship],
        metrics: list[QualityMetricSnapshot],
    ) -> list[str]:
        return [
            *[f"raw_asset_chunk:{item.id}" for item in chunks[:12]],
            *[f"context_object:{item.id}" for item in objects[:12]],
            *[f"context_relationship:{item.id}" for item in relationships[:12]],
            *[f"quality_metric:{item.id}" for item in metrics[:12]],
        ]

    @staticmethod
    def _context_projection(
        selected_refs: list[str],
        *,
        sources: list[RawAssetRecord],
        chunks: list[RawAssetChunk],
        objects: list[KnowledgeObject],
        relationships: list[ContextRelationship],
        metrics: list[QualityMetricSnapshot],
    ) -> dict[str, list[str]]:
        selected_chunk_ids = {
            ref.removeprefix("raw_asset_chunk:")
            for ref in selected_refs
            if ref.startswith("raw_asset_chunk:")
        }
        selected_object_ids = {
            ref.removeprefix("context_object:")
            for ref in selected_refs
            if ref.startswith("context_object:")
        }
        selected_source_ids = {
            ref.removeprefix("raw_asset:")
            for ref in selected_refs
            if ref.startswith("raw_asset:")
        }
        selected_relationship_ids = {
            ref.removeprefix("context_relationship:")
            for ref in selected_refs
            if ref.startswith("context_relationship:")
        }
        selected_metric_ids = {
            ref.removeprefix("quality_metric:")
            for ref in selected_refs
            if ref.startswith("quality_metric:")
        }

        chunks_by_id = {item.id: item for item in chunks}
        for chunk_id in selected_chunk_ids:
            chunk = chunks_by_id.get(chunk_id)
            if chunk is not None:
                selected_source_ids.add(chunk.raw_asset_id)

        if selected_source_ids:
            selected_object_ids.update(
                item.id
                for item in objects
                if any(source_id in item.evidence for source_id in selected_source_ids)
            )
        if not selected_object_ids:
            selected_object_ids.update(item.id for item in objects[:12])

        selected_relationship_ids.update(
            item.id
            for item in relationships
            if item.from_object_id in selected_object_ids or item.to_object_id in selected_object_ids
        )
        if not selected_relationship_ids:
            selected_relationship_ids.update(item.id for item in relationships[:12])

        for item in relationships:
            if item.id in selected_relationship_ids:
                selected_source_ids.update(ref for ref in item.source_refs if ref.startswith("raw_"))
        if not selected_source_ids:
            selected_source_ids.update(item.id for item in sources if item.ingestion_status == "indexed")

        selected_metric_ids.update(
            item.id
            for item in metrics
            if selected_source_ids.intersection(item.evidence_refs)
        )
        if not selected_metric_ids:
            selected_metric_ids.update(item.id for item in metrics[:12])

        evidence_refs: set[str] = set()
        for source in sources:
            if source.id in selected_source_ids:
                evidence_refs.update(source.evidence_refs)
        for chunk in chunks:
            if chunk.id in selected_chunk_ids:
                evidence_refs.update((f"raw_asset_chunk:{chunk.id}", chunk.content_ref))
        for item in objects:
            if item.id in selected_object_ids:
                evidence_refs.update(item.evidence)
        for item in relationships:
            if item.id in selected_relationship_ids:
                evidence_refs.update(item.source_refs)
        for item in metrics:
            if item.id in selected_metric_ids:
                evidence_refs.update(item.evidence_refs)

        return {
            "source_refs": sorted(selected_source_ids),
            "chunk_refs": sorted(selected_chunk_ids),
            "object_refs": sorted(selected_object_ids)[:24],
            "relationship_refs": sorted(selected_relationship_ids)[:24],
            "metric_refs": sorted(selected_metric_ids)[:24],
            "evidence_refs": sorted(evidence_refs),
        }

    @staticmethod
    def candidate_text(
        ref: str,
        sources: list[RawAssetRecord],
        chunks: list[RawAssetChunk],
        objects: list[KnowledgeObject],
        relationships: list[ContextRelationship],
        metrics: list[QualityMetricSnapshot],
    ) -> str:
        chunk_id = ref.removeprefix("raw_asset_chunk:") if ref.startswith("raw_asset_chunk:") else ref
        chunk = next((item for item in chunks if item.id == chunk_id), None)
        if chunk:
            return "\n".join([
                chunk.source_type,
                chunk.chunk_kind,
                chunk.section_path,
                chunk.content_hash,
            ])
        source_id = ref.removeprefix("raw_asset:") if ref.startswith("raw_asset:") else ref
        source = next((item for item in sources if item.id == source_id), None)
        if source:
            return "\n".join([
                source.source_type,
                source.source_label or "",
                source.source_uri,
                source.content_hash,
                *source.evidence_refs[:8],
            ])
        object_id = ref.removeprefix("context_object:") if ref.startswith("context_object:") else ref
        object_by_id = {item.id: item for item in objects}
        if object_id in object_by_id:
            item = object_by_id[object_id]
            return "\n".join([item.type, item.name, item.branch, *item.evidence[:8], *item.relations[:8]])
        relationship_id = ref.removeprefix("context_relationship:") if ref.startswith("context_relationship:") else ref
        relationship = next((item for item in relationships if item.id == relationship_id), None)
        if relationship:
            return "\n".join([
                relationship.relationship_type,
                relationship.from_object_id,
                relationship.to_object_id,
                *relationship.source_refs[:8],
            ])
        metric_id = ref.removeprefix("quality_metric:") if ref.startswith("quality_metric:") else ref
        metric = next((item for item in metrics if item.id == metric_id), None)
        if metric:
            return "\n".join([metric.metric_group, str(metric.metrics), *metric.evidence_refs[:8]])
        return ref


__all__ = ["SystemImageQualityContextApplicationService"]
