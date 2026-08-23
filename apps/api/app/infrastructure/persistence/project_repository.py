from __future__ import annotations

from sqlalchemy import delete, func, select, update

from .db_models import ProjectRecord, VersionRecord
from .quality_loop_repository import QualityLoopRepository
from .system_image_repository import SystemImageRepository
from .unit_of_work import session_scope
from ...application.quality_loop.quality_models import (
    ApprovalDetail,
    ApprovalSummary,
    AssetLane,
    ExecutionEvidence,
    FailureReport,
    QualityAssetPack,
    ReleaseDecision,
    ReleaseReadiness,
    RunDetail,
    RunSummary,
    USItem,
)
from ...application.quality_loop.governance_models import MergedResolution
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
from ...application.platform.project_models import ProjectCard, VersionSummary

__all__ = ["ProjectRepository"]


class ProjectRepository:
    def __init__(
        self,
        system_image_repository: SystemImageRepository | None = None,
        quality_loop_repository: QualityLoopRepository | None = None,
    ) -> None:
        self._system_image_repository = system_image_repository or SystemImageRepository()
        self._quality_loop_repository = quality_loop_repository or QualityLoopRepository()
    def list_projects(self) -> list[ProjectCard]:
        with session_scope() as session:
            rows = session.scalars(select(ProjectRecord).order_by(ProjectRecord.name, ProjectRecord.id)).all()
        return [self._to_project(row) for row in rows]

    def load_projects(self) -> list[ProjectCard]:
        return self.list_projects()

    def get_project(self, project_id: str) -> ProjectCard | None:
        with session_scope() as session:
            row = session.get(ProjectRecord, project_id)
            return self._to_project(row) if row is not None else None

    def load_versions(self) -> dict[str, list[VersionSummary]]:
        with session_scope() as session:
            rows = session.scalars(select(VersionRecord).order_by(VersionRecord.project_id, VersionRecord.sort_order)).all()
        grouped: dict[str, list[VersionSummary]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_version(row))
        return grouped

    def list_versions(self, project_id: str) -> list[VersionSummary]:
        with session_scope() as session:
            rows = session.scalars(
                select(VersionRecord)
                .where(VersionRecord.project_id == project_id)
                .order_by(VersionRecord.sort_order, VersionRecord.id)
            ).all()
        return [self._to_version(row) for row in rows]

    def load_us_items(self) -> dict[str, list[USItem]]:
        return self._quality_loop_repository.load_us_items()

    def list_us_items(
        self,
        project_id: str,
        version_id: str | None = None,
    ) -> list[USItem]:
        return self._quality_loop_repository.list_us_items(project_id, version_id)

    def load_asset_lanes(self) -> dict[str, list[AssetLane]]:
        return self._quality_loop_repository.load_asset_lanes()

    def load_runs(self) -> tuple[dict[str, list[RunSummary]], dict[str, RunDetail]]:
        return self._quality_loop_repository.load_runs()

    def load_approvals(self) -> tuple[dict[str, list[ApprovalSummary]], dict[str, ApprovalDetail]]:
        return self._quality_loop_repository.load_approvals()

    def load_knowledge_objects(self) -> dict[str, list[KnowledgeObject]]:
        return self._system_image_repository.load_knowledge_objects()

    def load_raw_assets(self) -> dict[str, list[RawAssetRecord]]:
        return self._system_image_repository.load_raw_assets()

    def load_raw_asset_chunks(self) -> dict[str, list[RawAssetChunk]]:
        return self._system_image_repository.load_raw_asset_chunks()

    def load_baselines(self) -> dict[str, list[BaselineRecord]]:
        return self._system_image_repository.load_baselines()

    def load_context_relationships(self) -> dict[str, list[ContextRelationship]]:
        return self._system_image_repository.load_context_relationships()

    def load_context_object_overlays(self) -> dict[str, list[ContextObjectOverlay]]:
        return self._system_image_repository.load_context_object_overlays()

    def load_quality_metric_snapshots(self) -> dict[str, list[QualityMetricSnapshot]]:
        return self._system_image_repository.load_quality_metric_snapshots()

    def load_retrieval_runs(self) -> dict[str, list[RetrievalRun]]:
        return self._system_image_repository.load_retrieval_runs()

    def load_embedding_records(self) -> dict[str, list[EmbeddingRecord]]:
        return self._system_image_repository.load_embedding_records()

    def load_rerank_records(self) -> dict[str, list[RerankModel]]:
        return self._system_image_repository.load_rerank_records()

    def load_task_contexts(self) -> dict[str, list[TaskContext]]:
        return self._system_image_repository.load_task_contexts()

    def load_quality_profiles(self) -> dict[str, list[QualityProfile]]:
        return self._system_image_repository.load_quality_profiles()

    def load_quality_asset_packs(self) -> dict[str, QualityAssetPack]:
        return self._quality_loop_repository.load_quality_asset_packs()

    def load_execution_evidence(self) -> dict[str, list[ExecutionEvidence]]:
        return self._quality_loop_repository.load_execution_evidence()

    def load_failure_reports(self) -> dict[str, list[FailureReport]]:
        return self._quality_loop_repository.load_failure_reports()

    def load_release_decisions(self) -> dict[str, ReleaseDecision]:
        return self._quality_loop_repository.load_release_decisions()

    def load_release_readiness(self) -> dict[str, ReleaseReadiness]:
        return self._quality_loop_repository.load_release_readiness()

    def load_merged_resolutions(self) -> dict[str, MergedResolution]:
        return self._quality_loop_repository.load_merged_resolutions()

    def upsert_project(self, project: ProjectCard) -> None:
        with session_scope() as session:
            row = session.get(ProjectRecord, project.id)
            if row is None:
                row = ProjectRecord(id=project.id)
                session.add(row)
            row.name = project.name
            row.code = project.code
            row.summary = project.summary
            row.status = project.status
            row.risk = project.risk
            row.progress = project.progress
            row.active_version = project.active_version
            row.blocked_items = project.blocked_items
            row.pending_approvals = project.pending_approvals
            row.system_image_status = project.system_image_status

    def upsert_version(self, project_id: str, version: VersionSummary, sort_order: int = 0) -> None:
        with session_scope() as session:
            row = session.get(VersionRecord, version.id)
            if row is None:
                row = VersionRecord(id=version.id, project_id=project_id)
                session.add(row)
            row.project_id = project_id
            row.name = version.name
            row.status = version.status
            row.branch_name = version.branch_name
            row.us_total = version.us_total
            row.us_closed = version.us_closed
            row.pending_runs = version.pending_runs
            row.pending_approvals = version.pending_approvals
            row.sort_order = sort_order

    def prepend_version(self, project_id: str, version: VersionSummary) -> None:
        with session_scope() as session:
            session.execute(
                update(VersionRecord)
                .where(VersionRecord.project_id == project_id)
                .values(sort_order=VersionRecord.sort_order + 1)
            )
            row = session.get(VersionRecord, version.id)
            if row is not None and row.project_id != project_id:
                raise ValueError(
                    f"Version {version.id!r} belongs to another project"
                )
            if row is None:
                row = VersionRecord(id=version.id, project_id=project_id)
                session.add(row)
            self._assign_version(row, project_id, version, sort_order=0)

    def save_version(self, project_id: str, version: VersionSummary) -> None:
        with session_scope() as session:
            row = session.get(VersionRecord, version.id)
            if row is not None and row.project_id != project_id:
                raise ValueError(
                    f"Version {version.id!r} belongs to another project"
                )
            if row is None:
                minimum_order = session.scalar(
                    select(func.min(VersionRecord.sort_order)).where(
                        VersionRecord.project_id == project_id
                    )
                )
                row = VersionRecord(
                    id=version.id,
                    project_id=project_id,
                    sort_order=(minimum_order - 1) if minimum_order is not None else 0,
                )
                session.add(row)
            self._assign_version(
                row,
                project_id,
                version,
                sort_order=row.sort_order,
            )

    def replace_versions(self, project_id: str, versions: list[VersionSummary]) -> None:
        with session_scope() as session:
            session.execute(delete(VersionRecord).where(VersionRecord.project_id == project_id))
            for sort_order, version in enumerate(versions):
                session.add(
                    VersionRecord(
                        id=version.id,
                        project_id=project_id,
                        name=version.name,
                        status=version.status,
                        branch_name=version.branch_name,
                        us_total=version.us_total,
                        us_closed=version.us_closed,
                        pending_runs=version.pending_runs,
                        pending_approvals=version.pending_approvals,
                        sort_order=sort_order,
                    )
                )

    def replace_us_items(self, project_id: str, version_id: str | None, items: list[USItem]) -> None:
        self._quality_loop_repository.replace_us_items(project_id, version_id, items)

    def upsert_us_item(self, project_id: str, version_id: str | None, item: USItem) -> None:
        self._quality_loop_repository.upsert_us_item(project_id, version_id, item)

    def replace_asset_lanes(self, project_id: str, us_id: str, lanes: list[AssetLane]) -> None:
        self._quality_loop_repository.replace_asset_lanes(project_id, us_id, lanes)

    def replace_runs(self, project_id: str, runs: list[RunDetail]) -> None:
        self._quality_loop_repository.replace_runs(project_id, runs)

    def replace_approvals(self, project_id: str, approvals: list[ApprovalDetail]) -> None:
        self._quality_loop_repository.replace_approvals(project_id, approvals)

    def replace_knowledge_objects(self, project_id: str, objects: list[KnowledgeObject]) -> None:
        self._system_image_repository.replace_knowledge_objects(project_id, objects)

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
        self._system_image_repository.replace_system_image(
            project_id,
            sources=sources,
            chunks=chunks,
            baselines=baselines,
            relationships=relationships,
            overlays=overlays,
            metric_snapshots=metric_snapshots,
            embedding_records=embedding_records,
            retrieval_runs=retrieval_runs,
            rerank_records=rerank_records,
            task_contexts=task_contexts,
            quality_profiles=quality_profiles,
            knowledge_objects=knowledge_objects,
        )

    def upsert_quality_asset_pack(self, pack: QualityAssetPack, sort_order: int = 0) -> None:
        self._quality_loop_repository.upsert_quality_asset_pack(pack, sort_order)

    def replace_execution_evidence(self, project_id: str, evidence: list[ExecutionEvidence]) -> None:
        self._quality_loop_repository.replace_execution_evidence(project_id, evidence)

    def replace_failure_reports(self, project_id: str, reports: list[FailureReport]) -> None:
        self._quality_loop_repository.replace_failure_reports(project_id, reports)

    def upsert_release_decision(self, decision: ReleaseDecision) -> None:
        self._quality_loop_repository.upsert_release_decision(decision)

    def upsert_release_readiness(self, project_id: str, readiness: ReleaseReadiness) -> None:
        self._quality_loop_repository.upsert_release_readiness(project_id, readiness)

    def upsert_merged_resolution(self, resolution: MergedResolution) -> None:
        self._quality_loop_repository.upsert_merged_resolution(resolution)

    @staticmethod
    def _assign_version(
        row: VersionRecord,
        project_id: str,
        version: VersionSummary,
        *,
        sort_order: int,
    ) -> None:
        row.project_id = project_id
        row.name = version.name
        row.status = version.status
        row.branch_name = version.branch_name
        row.us_total = version.us_total
        row.us_closed = version.us_closed
        row.pending_runs = version.pending_runs
        row.pending_approvals = version.pending_approvals
        row.sort_order = sort_order

    @staticmethod
    def _to_project(row: ProjectRecord) -> ProjectCard:
        return ProjectCard(
            id=row.id,
            name=row.name,
            code=row.code,
            summary=row.summary,
            status=row.status,
            risk=row.risk,
            progress=row.progress,
            active_version=row.active_version,
            blocked_items=row.blocked_items,
            pending_approvals=row.pending_approvals,
            system_image_status=row.system_image_status,
        )

    @staticmethod
    def _to_version(row: VersionRecord) -> VersionSummary:
        return VersionSummary(
            id=row.id,
            name=row.name,
            status=row.status,
            branch_name=row.branch_name,
            us_total=row.us_total,
            us_closed=row.us_closed,
            pending_runs=row.pending_runs,
            pending_approvals=row.pending_approvals,
        )
