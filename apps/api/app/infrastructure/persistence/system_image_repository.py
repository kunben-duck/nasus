from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, select

from .db_models import (
    BaselineRecord as BaselineRow,
    ContextObjectOverlayRecord,
    ContextRelationshipRecord,
    EmbeddingRecord as EmbeddingRow,
    KnowledgeObjectRecord,
    QualityProfileRecord,
    QualityMetricSnapshotRecord,
    RawAssetChunkRecord,
    RawAssetRecord as RawAssetRow,
    RerankRecord,
    RetrievalRunRecord,
    TaskContextRecord,
)
from .unit_of_work import session_scope
from ...application.system_image.system_image_models import (
    BaselineRecord,
    ContextObjectOverlay,
    ContextRelationship,
    EmbeddingRecord,
    KnowledgeObject,
    QualityProfile,
    QualityMetricSnapshot,
    RawAssetChunk,
    RawAssetRecord,
    RerankRecord as RerankModel,
    RetrievalRun,
    TaskContext,
)

__all__ = ["SystemImageProjectSnapshot", "SystemImageRepository"]


@dataclass(frozen=True)
class SystemImageProjectSnapshot:
    knowledge_objects: list[KnowledgeObject]
    raw_assets: list[RawAssetRecord]
    raw_asset_chunks: list[RawAssetChunk]
    baselines: list[BaselineRecord]
    relationships: list[ContextRelationship]
    overlays: list[ContextObjectOverlay]
    metric_snapshots: list[QualityMetricSnapshot]
    embedding_records: list[EmbeddingRecord]
    retrieval_runs: list[RetrievalRun]
    rerank_records: list[RerankModel]
    task_contexts: list[TaskContext]
    quality_profiles: list[QualityProfile]


class SystemImageRepository:

    def has_raw_assets(self, project_id: str) -> bool:
        with session_scope() as session:
            return bool(
                session.scalar(
                    select(func.count(RawAssetRow.id)).where(
                        RawAssetRow.project_id == project_id
                    )
                )
            )

    def load_project_snapshot(self, project_id: str) -> SystemImageProjectSnapshot:
        """Load one project projection without scanning unrelated tenants."""

        with session_scope() as session:
            knowledge_rows = session.scalars(
                select(KnowledgeObjectRecord)
                .where(KnowledgeObjectRecord.project_id == project_id)
                .order_by(KnowledgeObjectRecord.sort_order, KnowledgeObjectRecord.id)
            ).all()
            source_rows = session.scalars(
                select(RawAssetRow)
                .where(RawAssetRow.project_id == project_id)
                .order_by(RawAssetRow.sort_order, RawAssetRow.id)
            ).all()
            chunk_rows = session.scalars(
                select(RawAssetChunkRecord)
                .where(RawAssetChunkRecord.project_id == project_id)
                .order_by(RawAssetChunkRecord.sort_order, RawAssetChunkRecord.id)
            ).all()
            baseline_rows = session.scalars(
                select(BaselineRow)
                .where(BaselineRow.project_id == project_id)
                .order_by(BaselineRow.sort_order, BaselineRow.id)
            ).all()
            relationship_rows = session.scalars(
                select(ContextRelationshipRecord)
                .where(ContextRelationshipRecord.project_id == project_id)
                .order_by(ContextRelationshipRecord.sort_order, ContextRelationshipRecord.id)
            ).all()
            overlay_rows = session.scalars(
                select(ContextObjectOverlayRecord)
                .where(ContextObjectOverlayRecord.project_id == project_id)
                .order_by(ContextObjectOverlayRecord.sort_order, ContextObjectOverlayRecord.id)
            ).all()
            metric_rows = session.scalars(
                select(QualityMetricSnapshotRecord)
                .where(QualityMetricSnapshotRecord.project_id == project_id)
                .order_by(QualityMetricSnapshotRecord.sort_order, QualityMetricSnapshotRecord.id)
            ).all()
            embedding_rows = session.scalars(
                select(EmbeddingRow)
                .where(EmbeddingRow.project_id == project_id)
                .order_by(EmbeddingRow.sort_order, EmbeddingRow.id)
            ).all()
            retrieval_rows = session.scalars(
                select(RetrievalRunRecord)
                .where(RetrievalRunRecord.project_id == project_id)
                .order_by(RetrievalRunRecord.sort_order, RetrievalRunRecord.id)
            ).all()
            rerank_rows = session.scalars(
                select(RerankRecord)
                .where(RerankRecord.project_id == project_id)
                .order_by(RerankRecord.sort_order, RerankRecord.id)
            ).all()
            task_context_rows = session.scalars(
                select(TaskContextRecord)
                .where(TaskContextRecord.project_id == project_id)
                .order_by(TaskContextRecord.sort_order, TaskContextRecord.id)
            ).all()
            quality_profile_rows = session.scalars(
                select(QualityProfileRecord)
                .where(QualityProfileRecord.project_id == project_id)
                .order_by(QualityProfileRecord.sort_order, QualityProfileRecord.id)
            ).all()

        return SystemImageProjectSnapshot(
            knowledge_objects=[self._to_knowledge_object(row) for row in knowledge_rows],
            raw_assets=[self._to_raw_asset(row) for row in source_rows],
            raw_asset_chunks=[self._to_raw_asset_chunk(row) for row in chunk_rows],
            baselines=[self._to_baseline(row) for row in baseline_rows],
            relationships=[self._to_context_relationship(row) for row in relationship_rows],
            overlays=[self._to_context_object_overlay(row) for row in overlay_rows],
            metric_snapshots=[self._to_quality_metric_snapshot(row) for row in metric_rows],
            embedding_records=[self._to_embedding_record(row) for row in embedding_rows],
            retrieval_runs=[self._to_retrieval_run(row) for row in retrieval_rows],
            rerank_records=[self._to_rerank_record(row) for row in rerank_rows],
            task_contexts=[self._to_task_context(row) for row in task_context_rows],
            quality_profiles=[self._to_quality_profile(row) for row in quality_profile_rows],
        )

    def load_knowledge_objects(self) -> dict[str, list[KnowledgeObject]]:
        with session_scope() as session:
            rows = session.scalars(
                select(KnowledgeObjectRecord).order_by(KnowledgeObjectRecord.project_id, KnowledgeObjectRecord.sort_order)
            ).all()
        grouped: dict[str, list[KnowledgeObject]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_knowledge_object(row))
        return grouped

    def load_raw_assets(self) -> dict[str, list[RawAssetRecord]]:
        with session_scope() as session:
            rows = session.scalars(
                select(RawAssetRow).order_by(RawAssetRow.project_id, RawAssetRow.sort_order)
            ).all()
        grouped: dict[str, list[RawAssetRecord]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_raw_asset(row))
        return grouped

    def load_raw_asset_chunks(self) -> dict[str, list[RawAssetChunk]]:
        with session_scope() as session:
            rows = session.scalars(
                select(RawAssetChunkRecord).order_by(
                    RawAssetChunkRecord.project_id,
                    RawAssetChunkRecord.sort_order,
                )
            ).all()
        grouped: dict[str, list[RawAssetChunk]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_raw_asset_chunk(row))
        return grouped

    def load_baselines(self) -> dict[str, list[BaselineRecord]]:
        with session_scope() as session:
            rows = session.scalars(
                select(BaselineRow).order_by(BaselineRow.project_id, BaselineRow.sort_order)
            ).all()
        grouped: dict[str, list[BaselineRecord]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_baseline(row))
        return grouped

    def load_context_relationships(self) -> dict[str, list[ContextRelationship]]:
        with session_scope() as session:
            rows = session.scalars(
                select(ContextRelationshipRecord).order_by(
                    ContextRelationshipRecord.project_id,
                    ContextRelationshipRecord.sort_order,
                )
            ).all()
        grouped: dict[str, list[ContextRelationship]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_context_relationship(row))
        return grouped

    def load_context_object_overlays(self) -> dict[str, list[ContextObjectOverlay]]:
        with session_scope() as session:
            rows = session.scalars(
                select(ContextObjectOverlayRecord).order_by(
                    ContextObjectOverlayRecord.project_id,
                    ContextObjectOverlayRecord.sort_order,
                )
            ).all()
        grouped: dict[str, list[ContextObjectOverlay]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_context_object_overlay(row))
        return grouped

    def load_quality_metric_snapshots(self) -> dict[str, list[QualityMetricSnapshot]]:
        with session_scope() as session:
            rows = session.scalars(
                select(QualityMetricSnapshotRecord).order_by(
                    QualityMetricSnapshotRecord.project_id,
                    QualityMetricSnapshotRecord.sort_order,
                )
            ).all()
        grouped: dict[str, list[QualityMetricSnapshot]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_quality_metric_snapshot(row))
        return grouped

    def load_retrieval_runs(self) -> dict[str, list[RetrievalRun]]:
        with session_scope() as session:
            rows = session.scalars(
                select(RetrievalRunRecord).order_by(
                    RetrievalRunRecord.project_id,
                    RetrievalRunRecord.sort_order,
                )
            ).all()
        grouped: dict[str, list[RetrievalRun]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_retrieval_run(row))
        return grouped

    def load_embedding_records(self) -> dict[str, list[EmbeddingRecord]]:
        with session_scope() as session:
            rows = session.scalars(
                select(EmbeddingRow).order_by(
                    EmbeddingRow.project_id,
                    EmbeddingRow.sort_order,
                )
            ).all()
        grouped: dict[str, list[EmbeddingRecord]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_embedding_record(row))
        return grouped

    def load_rerank_records(self) -> dict[str, list[RerankModel]]:
        with session_scope() as session:
            rows = session.scalars(
                select(RerankRecord).order_by(
                    RerankRecord.project_id,
                    RerankRecord.sort_order,
                )
            ).all()
        grouped: dict[str, list[RerankModel]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_rerank_record(row))
        return grouped

    def load_task_contexts(self) -> dict[str, list[TaskContext]]:
        with session_scope() as session:
            rows = session.scalars(
                select(TaskContextRecord).order_by(
                    TaskContextRecord.project_id,
                    TaskContextRecord.sort_order,
                )
            ).all()
        grouped: dict[str, list[TaskContext]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_task_context(row))
        return grouped

    def list_task_contexts(self, project_id: str) -> list[TaskContext]:
        with session_scope() as session:
            rows = session.scalars(
                select(TaskContextRecord)
                .where(TaskContextRecord.project_id == project_id)
                .order_by(TaskContextRecord.sort_order, TaskContextRecord.id)
            ).all()
        return [self._to_task_context(row) for row in rows]

    def load_quality_profiles(self) -> dict[str, list[QualityProfile]]:
        with session_scope() as session:
            rows = session.scalars(
                select(QualityProfileRecord).order_by(
                    QualityProfileRecord.project_id,
                    QualityProfileRecord.sort_order,
                )
            ).all()
        grouped: dict[str, list[QualityProfile]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_quality_profile(row))
        return grouped

    def list_quality_profiles(self, project_id: str) -> list[QualityProfile]:
        with session_scope() as session:
            rows = session.scalars(
                select(QualityProfileRecord)
                .where(QualityProfileRecord.project_id == project_id)
                .order_by(QualityProfileRecord.sort_order, QualityProfileRecord.id)
            ).all()
        return [self._to_quality_profile(row) for row in rows]

    def replace_knowledge_objects(self, project_id: str, objects: list[KnowledgeObject]) -> None:
        with session_scope() as session:
            session.execute(delete(KnowledgeObjectRecord).where(KnowledgeObjectRecord.project_id == project_id))
            for sort_order, item in enumerate(objects):
                session.add(
                    KnowledgeObjectRecord(
                        id=item.id,
                        project_id=project_id,
                        name=item.name,
                        type=item.type,
                        branch=item.branch,
                        confidence=item.confidence,
                        relations=item.relations,
                        evidence=item.evidence,
                        freshness=item.freshness,
                        sort_order=sort_order,
                    )
                )

    def replace_embedding_records(self, project_id: str, records: list[EmbeddingRecord]) -> None:
        """Atomically replace the queryable vector projection for one project."""

        with session_scope() as session:
            session.execute(delete(EmbeddingRow).where(EmbeddingRow.project_id == project_id))
            for sort_order, record in enumerate(records):
                session.add(self._new_embedding_row(record, sort_order))

    def append_retrieval_trace(
        self,
        project_id: str,
        retrieval: RetrievalRun,
        rerank: RerankModel | None,
    ) -> None:
        """Atomically append one Agent retrieval and its rerank evidence."""

        if retrieval.project_id != project_id:
            raise ValueError("retrieval project_id does not match the repository scope")
        if rerank is not None and rerank.project_id != project_id:
            raise ValueError("rerank project_id does not match the repository scope")
        if rerank is not None and rerank.retrieval_run_id != retrieval.id:
            raise ValueError("rerank retrieval_run_id does not match the retrieval trace")

        with session_scope() as session:
            retrieval_sort_order = int(
                session.scalar(
                    select(func.coalesce(func.max(RetrievalRunRecord.sort_order), -1)).where(
                        RetrievalRunRecord.project_id == project_id
                    )
                )
                or 0
            ) + 1
            session.add(
                RetrievalRunRecord(
                    id=retrieval.id,
                    project_id=project_id,
                    baseline_id=retrieval.baseline_id,
                    version_id=retrieval.version_id,
                    us_id=retrieval.us_id,
                    query=retrieval.query,
                    strategy=retrieval.strategy,
                    candidate_count=retrieval.candidate_count,
                    result_refs=retrieval.result_refs,
                    embedding_record_ids=retrieval.embedding_record_ids,
                    rerank_record_id=retrieval.rerank_record_id,
                    fallback_used=retrieval.fallback_used,
                    created_at=retrieval.created_at,
                    sort_order=retrieval_sort_order,
                )
            )
            if rerank is None:
                return
            rerank_sort_order = int(
                session.scalar(
                    select(func.coalesce(func.max(RerankRecord.sort_order), -1)).where(
                        RerankRecord.project_id == project_id
                    )
                )
                or 0
            ) + 1
            session.add(
                RerankRecord(
                    id=rerank.id,
                    project_id=project_id,
                    retrieval_run_id=retrieval.id,
                    rerank_model=rerank.rerank_model,
                    rerank_version=rerank.rerank_version,
                    input_count=rerank.input_count,
                    output_count=rerank.output_count,
                    status=rerank.status,
                    latency_ms=rerank.latency_ms,
                    fallback_reason=rerank.fallback_reason,
                    created_at=rerank.created_at,
                    sort_order=rerank_sort_order,
                )
            )

    def replace_system_image(
        self,
        project_id: str,
        *,
        sources: list[RawAssetRecord],
        chunks: list[RawAssetChunk],
        baselines: list[BaselineRecord],
        relationships: list[ContextRelationship],
        overlays: list[ContextObjectOverlay],
        metric_snapshots: list[QualityMetricSnapshot],
        embedding_records: list[EmbeddingRecord],
        retrieval_runs: list[RetrievalRun],
        rerank_records: list[RerankModel],
        task_contexts: list[TaskContext],
        quality_profiles: list[QualityProfile],
        knowledge_objects: list[KnowledgeObject] | None = None,
    ) -> None:
        with session_scope() as session:
            if knowledge_objects is not None:
                session.execute(
                    delete(KnowledgeObjectRecord).where(
                        KnowledgeObjectRecord.project_id == project_id
                    )
                )
            session.execute(delete(RawAssetRow).where(RawAssetRow.project_id == project_id))
            session.execute(delete(RawAssetChunkRecord).where(RawAssetChunkRecord.project_id == project_id))
            session.execute(delete(BaselineRow).where(BaselineRow.project_id == project_id))
            session.execute(delete(ContextRelationshipRecord).where(ContextRelationshipRecord.project_id == project_id))
            session.execute(delete(ContextObjectOverlayRecord).where(ContextObjectOverlayRecord.project_id == project_id))
            session.execute(delete(QualityMetricSnapshotRecord).where(QualityMetricSnapshotRecord.project_id == project_id))
            session.execute(delete(EmbeddingRow).where(EmbeddingRow.project_id == project_id))
            session.execute(delete(RetrievalRunRecord).where(RetrievalRunRecord.project_id == project_id))
            session.execute(delete(RerankRecord).where(RerankRecord.project_id == project_id))
            session.execute(delete(TaskContextRecord).where(TaskContextRecord.project_id == project_id))
            session.execute(delete(QualityProfileRecord).where(QualityProfileRecord.project_id == project_id))

            for sort_order, item in enumerate(knowledge_objects or []):
                session.add(
                    KnowledgeObjectRecord(
                        id=item.id,
                        project_id=project_id,
                        name=item.name,
                        type=item.type,
                        branch=item.branch,
                        confidence=item.confidence,
                        relations=item.relations,
                        evidence=item.evidence,
                        freshness=item.freshness,
                        sort_order=sort_order,
                    )
                )

            for sort_order, source in enumerate(sources):
                session.add(
                    RawAssetRow(
                        id=source.id,
                        project_id=source.project_id,
                        version_id=source.version_id,
                        source_type=source.source_type,
                        source_uri=source.source_uri,
                        source_label=source.source_label,
                        ingestion_status=source.ingestion_status,
                        content_hash=source.content_hash,
                        content_ref=source.content_ref,
                        evidence_refs=source.evidence_refs,
                        registered_at=source.registered_at,
                        registered_by_actor=source.registered_by_actor,
                        registered_from_invocation_id=source.registered_from_invocation_id,
                        credential_ref=source.credential_ref,
                        permission_status=source.permission_status,
                        permission_checked_at=source.permission_checked_at,
                        ingest_started_at=source.ingest_started_at,
                        last_ingested_at=source.last_ingested_at,
                        failure_reason=source.failure_reason,
                        file_count=source.file_count,
                        byte_count=source.byte_count,
                        sort_order=sort_order,
                    )
                )

            for sort_order, chunk in enumerate(chunks):
                session.add(
                    RawAssetChunkRecord(
                        id=chunk.id,
                        project_id=chunk.project_id,
                        raw_asset_id=chunk.raw_asset_id,
                        source_type=chunk.source_type,
                        chunk_kind=chunk.chunk_kind,
                        section_path=chunk.section_path,
                        content_ref=chunk.content_ref,
                        content_hash=chunk.content_hash,
                        token_estimate=chunk.token_estimate,
                        chunk_metadata=chunk.metadata,
                        embedding_record_id=chunk.embedding_record_id,
                        created_at=chunk.created_at,
                        sort_order=sort_order,
                    )
                )

            for sort_order, baseline in enumerate(baselines):
                session.add(
                    BaselineRow(
                        id=baseline.id,
                        project_id=baseline.project_id,
                        kind=baseline.kind,
                        status=baseline.status,
                        source_version_id=baseline.source_version_id,
                        parent_baseline_id=baseline.parent_baseline_id,
                        fork_strategy=baseline.fork_strategy,
                        object_count=baseline.object_count,
                        relationship_count=baseline.relationship_count,
                        metric_snapshot_count=baseline.metric_snapshot_count,
                        updated_at=baseline.updated_at,
                        sort_order=sort_order,
                    )
                )

            for sort_order, relationship in enumerate(relationships):
                session.add(
                    ContextRelationshipRecord(
                        id=relationship.id,
                        project_id=relationship.project_id,
                        baseline_id=relationship.baseline_id,
                        from_object_id=relationship.from_object_id,
                        relationship_type=relationship.relationship_type,
                        to_object_id=relationship.to_object_id,
                        confidence=relationship.confidence,
                        source_refs=relationship.source_refs,
                        sort_order=sort_order,
                    )
                )

            for sort_order, overlay in enumerate(overlays):
                session.add(
                    ContextObjectOverlayRecord(
                        id=overlay.id,
                        project_id=overlay.project_id,
                        baseline_id=overlay.baseline_id,
                        object_id=overlay.object_id,
                        field_path=overlay.field_path,
                        operation=overlay.operation,
                        value_ref=overlay.value_ref,
                        source_refs=overlay.source_refs,
                        status=overlay.status,
                        sort_order=sort_order,
                    )
                )

            for sort_order, metric in enumerate(metric_snapshots):
                session.add(
                    QualityMetricSnapshotRecord(
                        id=metric.id,
                        project_id=metric.project_id,
                        baseline_id=metric.baseline_id,
                        version_id=metric.version_id,
                        us_id=metric.us_id,
                        task_id=metric.task_id,
                        metric_group=metric.metric_group,
                        metrics=metric.metrics,
                        evidence_refs=metric.evidence_refs,
                        captured_at=metric.captured_at,
                        sort_order=sort_order,
                    )
                )

            for sort_order, embedding in enumerate(embedding_records):
                session.add(self._new_embedding_row(embedding, sort_order))

            for sort_order, retrieval in enumerate(retrieval_runs):
                session.add(
                    RetrievalRunRecord(
                        id=retrieval.id,
                        project_id=retrieval.project_id,
                        baseline_id=retrieval.baseline_id,
                        version_id=retrieval.version_id,
                        us_id=retrieval.us_id,
                        query=retrieval.query,
                        strategy=retrieval.strategy,
                        candidate_count=retrieval.candidate_count,
                        result_refs=retrieval.result_refs,
                        embedding_record_ids=retrieval.embedding_record_ids,
                        rerank_record_id=retrieval.rerank_record_id,
                        fallback_used=retrieval.fallback_used,
                        created_at=retrieval.created_at,
                        sort_order=sort_order,
                    )
                )

            for sort_order, rerank in enumerate(rerank_records):
                session.add(
                    RerankRecord(
                        id=rerank.id,
                        project_id=rerank.project_id,
                        retrieval_run_id=rerank.retrieval_run_id,
                        rerank_model=rerank.rerank_model,
                        rerank_version=rerank.rerank_version,
                        input_count=rerank.input_count,
                        output_count=rerank.output_count,
                        status=rerank.status,
                        latency_ms=rerank.latency_ms,
                        fallback_reason=rerank.fallback_reason,
                        created_at=rerank.created_at,
                        sort_order=sort_order,
                    )
                )

            for sort_order, context in enumerate(task_contexts):
                session.add(
                    TaskContextRecord(
                        id=context.id,
                        project_id=context.project_id,
                        baseline_id=context.baseline_id,
                        version_id=context.version_id,
                        us_id=context.us_id,
                        retrieval_run_id=context.retrieval_run_id,
                        summary=context.summary,
                        readiness=context.readiness,
                        source_refs=context.source_refs,
                        object_refs=context.object_refs,
                        relationship_refs=context.relationship_refs,
                        metric_refs=context.metric_refs,
                        evidence_refs=context.evidence_refs,
                        missing_context=context.missing_context,
                        confidence=context.confidence,
                        freshness_at=context.freshness_at,
                        context_hash=context.context_hash,
                        sort_order=sort_order,
                    )
                )

            for sort_order, profile in enumerate(quality_profiles):
                session.add(
                    QualityProfileRecord(
                        id=profile.id,
                        project_id=profile.project_id,
                        baseline_id=profile.baseline_id,
                        version_id=profile.version_id,
                        us_id=profile.us_id,
                        task_context_id=profile.task_context_id,
                        risk_score=profile.risk_score,
                        coverage_score=profile.coverage_score,
                        release_score=profile.release_score,
                        automation_feasibility=profile.automation_feasibility,
                        risk_drivers=profile.risk_drivers,
                        regression_scope_refs=profile.regression_scope_refs,
                        evidence_refs=profile.evidence_refs,
                        confidence=profile.confidence,
                        freshness_at=profile.freshness_at,
                        sort_order=sort_order,
                    )
                )

    @staticmethod
    def _to_knowledge_object(row: KnowledgeObjectRecord) -> KnowledgeObject:
        return KnowledgeObject(
            id=row.id,
            name=row.name,
            type=row.type,
            branch=row.branch,
            confidence=row.confidence,
            relations=row.relations or [],
            evidence=row.evidence or [],
            freshness=row.freshness,
        )

    @staticmethod
    def _to_raw_asset(row: RawAssetRow) -> RawAssetRecord:
        return RawAssetRecord(
            id=row.id,
            project_id=row.project_id,
            version_id=row.version_id,
            source_type=row.source_type,  # type: ignore[arg-type]
            source_uri=row.source_uri,
            source_label=row.source_label,
            ingestion_status=row.ingestion_status,  # type: ignore[arg-type]
            content_hash=row.content_hash,
            content_ref=row.content_ref,
            evidence_refs=row.evidence_refs or [],
            registered_at=row.registered_at,
            registered_by_actor=row.registered_by_actor,  # type: ignore[arg-type]
            registered_from_invocation_id=row.registered_from_invocation_id,
            credential_ref=row.credential_ref,
            permission_status=row.permission_status,  # type: ignore[arg-type]
            permission_checked_at=row.permission_checked_at,
            ingest_started_at=row.ingest_started_at,
            last_ingested_at=row.last_ingested_at,
            failure_reason=row.failure_reason,
            file_count=row.file_count,
            byte_count=row.byte_count,
        )

    @staticmethod
    def _to_raw_asset_chunk(row: RawAssetChunkRecord) -> RawAssetChunk:
        return RawAssetChunk(
            id=row.id,
            project_id=row.project_id,
            raw_asset_id=row.raw_asset_id,
            source_type=row.source_type,  # type: ignore[arg-type]
            chunk_kind=row.chunk_kind,  # type: ignore[arg-type]
            section_path=row.section_path,
            content_ref=row.content_ref,
            content_hash=row.content_hash,
            token_estimate=row.token_estimate,
            metadata=row.chunk_metadata or {},
            embedding_record_id=row.embedding_record_id,
            created_at=row.created_at,
        )

    @staticmethod
    def _to_baseline(row: BaselineRow) -> BaselineRecord:
        return BaselineRecord(
            id=row.id,
            project_id=row.project_id,
            kind=row.kind,  # type: ignore[arg-type]
            status=row.status,  # type: ignore[arg-type]
            source_version_id=row.source_version_id,
            parent_baseline_id=row.parent_baseline_id,
            fork_strategy=row.fork_strategy,  # type: ignore[arg-type]
            object_count=row.object_count,
            relationship_count=row.relationship_count,
            metric_snapshot_count=row.metric_snapshot_count,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _to_context_relationship(row: ContextRelationshipRecord) -> ContextRelationship:
        return ContextRelationship(
            id=row.id,
            project_id=row.project_id,
            baseline_id=row.baseline_id,
            from_object_id=row.from_object_id,
            relationship_type=row.relationship_type,  # type: ignore[arg-type]
            to_object_id=row.to_object_id,
            confidence=row.confidence,
            source_refs=row.source_refs or [],
        )

    @staticmethod
    def _to_context_object_overlay(row: ContextObjectOverlayRecord) -> ContextObjectOverlay:
        return ContextObjectOverlay(
            id=row.id,
            project_id=row.project_id,
            baseline_id=row.baseline_id,
            object_id=row.object_id,
            field_path=row.field_path,
            operation=row.operation,  # type: ignore[arg-type]
            value_ref=row.value_ref,
            source_refs=row.source_refs or [],
            status=row.status,  # type: ignore[arg-type]
        )

    @staticmethod
    def _to_quality_metric_snapshot(row: QualityMetricSnapshotRecord) -> QualityMetricSnapshot:
        return QualityMetricSnapshot(
            id=row.id,
            project_id=row.project_id,
            baseline_id=row.baseline_id,
            version_id=row.version_id,
            us_id=row.us_id,
            task_id=row.task_id,
            metric_group=row.metric_group,  # type: ignore[arg-type]
            metrics=row.metrics or {},
            evidence_refs=row.evidence_refs or [],
            captured_at=row.captured_at,
        )

    @staticmethod
    def _to_retrieval_run(row: RetrievalRunRecord) -> RetrievalRun:
        return RetrievalRun(
            id=row.id,
            project_id=row.project_id,
            baseline_id=row.baseline_id,
            version_id=row.version_id,
            us_id=row.us_id,
            query=row.query,
            strategy=row.strategy,  # type: ignore[arg-type]
            candidate_count=row.candidate_count,
            result_refs=row.result_refs or [],
            embedding_record_ids=row.embedding_record_ids or [],
            rerank_record_id=row.rerank_record_id,
            fallback_used=row.fallback_used,
            created_at=row.created_at,
        )

    @staticmethod
    def _new_embedding_row(embedding: EmbeddingRecord, sort_order: int) -> EmbeddingRow:
        return EmbeddingRow(
            id=embedding.id,
            project_id=embedding.project_id,
            baseline_id=embedding.baseline_id,
            source_ref=embedding.source_ref,
            object_ref=embedding.object_ref,
            chunk_ref=embedding.chunk_ref,
            content_hash=embedding.content_hash,
            embedding_model=embedding.embedding_model,
            embedding_version=embedding.embedding_version,
            provider=embedding.provider,
            vector_ref=embedding.vector_ref,
            embedding_vector=embedding.embedding_vector or None,
            search_text=embedding.search_text,
            dimensions=embedding.dimensions,
            status=embedding.status,
            fallback_reason=embedding.fallback_reason,
            created_at=embedding.created_at,
            sort_order=sort_order,
        )

    @staticmethod
    def _to_embedding_record(row: EmbeddingRow) -> EmbeddingRecord:
        return EmbeddingRecord(
            id=row.id,
            project_id=row.project_id,
            baseline_id=row.baseline_id,
            source_ref=row.source_ref,
            object_ref=row.object_ref,
            chunk_ref=row.chunk_ref,
            content_hash=row.content_hash,
            embedding_model=row.embedding_model,
            embedding_version=row.embedding_version,
            provider=row.provider,  # type: ignore[arg-type]
            vector_ref=row.vector_ref,
            embedding_vector=[] if row.embedding_vector is None else [float(item) for item in row.embedding_vector],
            search_text=row.search_text or "",
            dimensions=row.dimensions,
            status=row.status,  # type: ignore[arg-type]
            fallback_reason=row.fallback_reason,
            created_at=row.created_at,
        )

    @staticmethod
    def _to_rerank_record(row: RerankRecord) -> RerankModel:
        return RerankModel(
            id=row.id,
            project_id=row.project_id,
            retrieval_run_id=row.retrieval_run_id,
            rerank_model=row.rerank_model,
            rerank_version=row.rerank_version,
            input_count=row.input_count,
            output_count=row.output_count,
            status=row.status,  # type: ignore[arg-type]
            latency_ms=row.latency_ms,
            fallback_reason=row.fallback_reason,
            created_at=row.created_at,
        )

    @staticmethod
    def _to_task_context(row: TaskContextRecord) -> TaskContext:
        return TaskContext(
            id=row.id,
            project_id=row.project_id,
            baseline_id=row.baseline_id,
            version_id=row.version_id,
            us_id=row.us_id,
            retrieval_run_id=row.retrieval_run_id,
            summary=row.summary,
            readiness=row.readiness,  # type: ignore[arg-type]
            source_refs=row.source_refs or [],
            object_refs=row.object_refs or [],
            relationship_refs=row.relationship_refs or [],
            metric_refs=row.metric_refs or [],
            evidence_refs=row.evidence_refs or [],
            missing_context=row.missing_context or [],
            confidence=row.confidence,
            freshness_at=row.freshness_at,
            context_hash=row.context_hash,
        )

    @staticmethod
    def _to_quality_profile(row: QualityProfileRecord) -> QualityProfile:
        return QualityProfile(
            id=row.id,
            project_id=row.project_id,
            baseline_id=row.baseline_id,
            version_id=row.version_id,
            us_id=row.us_id,
            task_context_id=row.task_context_id,
            risk_score=row.risk_score,
            coverage_score=row.coverage_score,
            release_score=row.release_score,
            automation_feasibility=row.automation_feasibility,
            risk_drivers=row.risk_drivers or [],
            regression_scope_refs=row.regression_scope_refs or [],
            evidence_refs=row.evidence_refs or [],
            confidence=row.confidence,
            freshness_at=row.freshness_at,
        )
