from __future__ import annotations

from sqlalchemy import delete, func, select

from .db_models import (
    ApprovalRecord,
    AssetLaneRecord,
    ExecutionEvidenceRecord,
    FailureReportRecord,
    MergedResolutionRecord,
    QualityAssetPackRecord,
    ReleaseDecisionRecord,
    ReleaseReadinessRecord,
    RunRecord,
    USWorkItemRecord,
)
from .unit_of_work import session_scope
from ...application.quality_loop.quality_models import (
    ApprovalDetail,
    ApprovalSummary,
    AssetLane,
    ExecutionEvidence,
    FailureReport,
    QualityAssetPack,
    QualityAssetPart,
    ReleaseDecision,
    ReleaseReadiness,
    RunDetail,
    RunSummary,
    USItem,
)
from ...application.quality_loop.governance_models import (
    ConflictEntry,
    MergedResolution,
)

__all__ = ["QualityLoopRepository"]


class QualityLoopRepository:
    def get_us_item(self, us_id: str) -> USItem | None:
        with session_scope() as session:
            row = session.get(USWorkItemRecord, us_id)
            return self._to_us_item(row) if row is not None else None

    def get_us_item_for_project(
        self,
        project_id: str,
        us_id: str,
    ) -> USItem | None:
        with session_scope() as session:
            row = session.scalar(
                select(USWorkItemRecord).where(
                    USWorkItemRecord.project_id == project_id,
                    USWorkItemRecord.id == us_id,
                )
            )
            return self._to_us_item(row) if row is not None else None

    def project_id_for_us(self, us_id: str) -> str | None:
        with session_scope() as session:
            return session.scalar(
                select(USWorkItemRecord.project_id).where(
                    USWorkItemRecord.id == us_id
                )
            )

    def version_id_for_us(self, project_id: str, us_id: str) -> str | None:
        with session_scope() as session:
            return session.scalar(
                select(USWorkItemRecord.version_id).where(
                    USWorkItemRecord.project_id == project_id,
                    USWorkItemRecord.id == us_id,
                )
            )

    def first_us_id(self, project_id: str) -> str | None:
        with session_scope() as session:
            return session.scalar(
                select(USWorkItemRecord.id)
                .where(USWorkItemRecord.project_id == project_id)
                .order_by(USWorkItemRecord.id)
                .limit(1)
            )

    def list_us_items(
        self,
        project_id: str,
        version_id: str | None = None,
    ) -> list[USItem]:
        with session_scope() as session:
            statement = select(USWorkItemRecord).where(
                USWorkItemRecord.project_id == project_id
            )
            if version_id is not None:
                statement = statement.where(
                    USWorkItemRecord.version_id == version_id
                )
            rows = session.scalars(statement.order_by(USWorkItemRecord.id)).all()
        return [self._to_us_item(row) for row in rows]

    def load_us_items(self) -> dict[str, list[USItem]]:
        with session_scope() as session:
            rows = session.scalars(select(USWorkItemRecord).order_by(USWorkItemRecord.project_id, USWorkItemRecord.id)).all()
        grouped: dict[str, list[USItem]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_us_item(row))
        return grouped

    def list_asset_lanes(self, project_id: str) -> dict[str, list[AssetLane]]:
        with session_scope() as session:
            rows = session.scalars(
                select(AssetLaneRecord)
                .where(AssetLaneRecord.project_id == project_id)
                .order_by(AssetLaneRecord.us_id, AssetLaneRecord.sort_order)
            ).all()
        grouped: dict[str, list[AssetLane]] = {}
        for row in rows:
            grouped.setdefault(row.us_id, []).append(self._to_asset_lane(row))
        return grouped

    def list_asset_lanes_for_us(self, us_id: str) -> list[AssetLane]:
        with session_scope() as session:
            rows = session.scalars(
                select(AssetLaneRecord)
                .where(AssetLaneRecord.us_id == us_id)
                .order_by(AssetLaneRecord.sort_order)
            ).all()
        return [self._to_asset_lane(row) for row in rows]

    def load_asset_lanes(self) -> dict[str, list[AssetLane]]:
        with session_scope() as session:
            rows = session.scalars(select(AssetLaneRecord).order_by(AssetLaneRecord.us_id, AssetLaneRecord.sort_order)).all()
        grouped: dict[str, list[AssetLane]] = {}
        for row in rows:
            grouped.setdefault(row.us_id, []).append(self._to_asset_lane(row))
        return grouped

    def list_runs(self, project_id: str) -> list[RunSummary]:
        with session_scope() as session:
            rows = session.scalars(
                select(RunRecord)
                .where(RunRecord.project_id == project_id)
                .order_by(RunRecord.sort_order, RunRecord.id)
            ).all()
        return [self._to_run_summary(row) for row in rows]

    def get_run_detail(self, project_id: str, run_id: str) -> RunDetail | None:
        with session_scope() as session:
            row = session.scalar(
                select(RunRecord).where(
                    RunRecord.project_id == project_id,
                    RunRecord.id == run_id,
                )
            )
            return self._to_run_detail(row) if row is not None else None

    def project_id_for_run(self, run_id: str) -> str | None:
        with session_scope() as session:
            return session.scalar(
                select(RunRecord.project_id).where(RunRecord.id == run_id)
            )

    def list_run_details(self, project_id: str) -> list[RunDetail]:
        with session_scope() as session:
            rows = session.scalars(
                select(RunRecord)
                .where(RunRecord.project_id == project_id)
                .order_by(RunRecord.sort_order, RunRecord.id)
            ).all()
        return [self._to_run_detail(row) for row in rows]

    def us_id_for_run_evidence(
        self,
        project_id: str,
        run_id: str,
    ) -> str | None:
        with session_scope() as session:
            return session.scalar(
                select(ExecutionEvidenceRecord.us_id)
                .where(
                    ExecutionEvidenceRecord.project_id == project_id,
                    ExecutionEvidenceRecord.run_id == run_id,
                    ExecutionEvidenceRecord.us_id.is_not(None),
                )
                .order_by(ExecutionEvidenceRecord.sort_order)
                .limit(1)
            )

    def load_runs(self) -> tuple[dict[str, list[RunSummary]], dict[str, RunDetail]]:
        with session_scope() as session:
            rows = session.scalars(select(RunRecord).order_by(RunRecord.project_id, RunRecord.sort_order)).all()
        grouped: dict[str, list[RunSummary]] = {}
        details: dict[str, RunDetail] = {}
        for row in rows:
            summary = self._to_run_summary(row)
            grouped.setdefault(row.project_id, []).append(summary)
            details[row.id] = self._to_run_detail(row)
        return grouped, details

    def list_approvals(self, project_id: str) -> list[ApprovalSummary]:
        with session_scope() as session:
            rows = session.scalars(
                select(ApprovalRecord)
                .where(ApprovalRecord.project_id == project_id)
                .order_by(ApprovalRecord.sort_order, ApprovalRecord.id)
            ).all()
        return [self._to_approval_summary(row) for row in rows]

    def get_approval_detail(self, project_id: str, approval_id: str) -> ApprovalDetail | None:
        with session_scope() as session:
            row = session.scalar(
                select(ApprovalRecord).where(
                    ApprovalRecord.project_id == project_id,
                    ApprovalRecord.id == approval_id,
                )
            )
            return self._to_approval_detail(row) if row is not None else None

    def load_approvals(self) -> tuple[dict[str, list[ApprovalSummary]], dict[str, ApprovalDetail]]:
        with session_scope() as session:
            rows = session.scalars(select(ApprovalRecord).order_by(ApprovalRecord.project_id, ApprovalRecord.sort_order)).all()
        grouped: dict[str, list[ApprovalSummary]] = {}
        details: dict[str, ApprovalDetail] = {}
        for row in rows:
            summary = self._to_approval_summary(row)
            grouped.setdefault(row.project_id, []).append(summary)
            details[row.id] = self._to_approval_detail(row)
        return grouped, details

    def load_merged_resolutions(self) -> dict[str, MergedResolution]:
        with session_scope() as session:
            rows = session.scalars(
                select(MergedResolutionRecord).order_by(
                    MergedResolutionRecord.created_at,
                    MergedResolutionRecord.id,
                )
            ).all()
        return {row.id: self._to_merged_resolution(row) for row in rows}

    def list_merged_resolutions(
        self,
        project_id: str,
        *,
        task_id: str | None = None,
    ) -> list[MergedResolution]:
        with session_scope() as session:
            statement = select(MergedResolutionRecord).where(
                MergedResolutionRecord.project_id == project_id
            )
            if task_id is not None:
                statement = statement.where(MergedResolutionRecord.task_id == task_id)
            rows = session.scalars(
                statement.order_by(
                    MergedResolutionRecord.updated_at.desc(),
                    MergedResolutionRecord.id.desc(),
                )
            ).all()
        return [self._to_merged_resolution(row) for row in rows]

    def get_merged_resolution(self, resolution_id: str) -> MergedResolution | None:
        with session_scope() as session:
            row = session.get(MergedResolutionRecord, resolution_id)
            return self._to_merged_resolution(row) if row is not None else None
    def load_quality_asset_packs(self) -> dict[str, QualityAssetPack]:
        with session_scope() as session:
            rows = session.scalars(
                select(QualityAssetPackRecord).order_by(
                    QualityAssetPackRecord.project_id,
                    QualityAssetPackRecord.sort_order,
                )
            ).all()
        return {row.id: self._to_quality_asset_pack(row) for row in rows}

    def list_quality_asset_packs(self, project_id: str) -> list[QualityAssetPack]:
        with session_scope() as session:
            rows = session.scalars(
                select(QualityAssetPackRecord)
                .where(QualityAssetPackRecord.project_id == project_id)
                .order_by(
                    QualityAssetPackRecord.updated_at,
                    QualityAssetPackRecord.id,
                )
            ).all()
        return [self._to_quality_asset_pack(row) for row in rows]

    def get_quality_asset_pack(
        self,
        project_id: str,
        us_id: str,
    ) -> QualityAssetPack | None:
        with session_scope() as session:
            row = session.scalar(
                select(QualityAssetPackRecord)
                .where(
                    QualityAssetPackRecord.project_id == project_id,
                    QualityAssetPackRecord.us_id == us_id,
                )
                .order_by(
                    QualityAssetPackRecord.updated_at.desc(),
                    QualityAssetPackRecord.id.desc(),
                )
                .limit(1)
            )
            return (
                self._to_quality_asset_pack(row)
                if row is not None
                else None
            )

    def load_execution_evidence(self) -> dict[str, list[ExecutionEvidence]]:
        with session_scope() as session:
            rows = session.scalars(
                select(ExecutionEvidenceRecord).order_by(
                    ExecutionEvidenceRecord.project_id,
                    ExecutionEvidenceRecord.sort_order,
                )
            ).all()
        grouped: dict[str, list[ExecutionEvidence]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_execution_evidence(row))
        return grouped

    def list_execution_evidence(
        self,
        project_id: str,
    ) -> list[ExecutionEvidence]:
        with session_scope() as session:
            rows = session.scalars(
                select(ExecutionEvidenceRecord)
                .where(ExecutionEvidenceRecord.project_id == project_id)
                .order_by(ExecutionEvidenceRecord.sort_order)
            ).all()
        return [self._to_execution_evidence(row) for row in rows]
    def load_failure_reports(self) -> dict[str, list[FailureReport]]:
        with session_scope() as session:
            rows = session.scalars(
                select(FailureReportRecord).order_by(
                    FailureReportRecord.project_id,
                    FailureReportRecord.sort_order,
                )
            ).all()
        grouped: dict[str, list[FailureReport]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_failure_report(row))
        return grouped

    def list_failure_reports(self, project_id: str) -> list[FailureReport]:
        with session_scope() as session:
            rows = session.scalars(
                select(FailureReportRecord)
                .where(FailureReportRecord.project_id == project_id)
                .order_by(FailureReportRecord.sort_order)
            ).all()
        return [self._to_failure_report(row) for row in rows]
    def load_release_decisions(self) -> dict[str, ReleaseDecision]:
        with session_scope() as session:
            rows = session.scalars(select(ReleaseDecisionRecord)).all()
        return {row.id: self._to_release_decision(row) for row in rows}

    def list_release_decisions(self, project_id: str) -> list[ReleaseDecision]:
        with session_scope() as session:
            rows = session.scalars(
                select(ReleaseDecisionRecord)
                .where(ReleaseDecisionRecord.project_id == project_id)
                .order_by(
                    ReleaseDecisionRecord.created_at,
                    ReleaseDecisionRecord.id,
                )
            ).all()
        return [self._to_release_decision(row) for row in rows]

    def find_release_decision(
        self,
        project_id: str,
        us_id: str | None = None,
        version_id: str | None = None,
    ) -> ReleaseDecision | None:
        with session_scope() as session:
            if version_id and us_id:
                exact = session.scalar(
                    select(ReleaseDecisionRecord)
                    .where(
                        ReleaseDecisionRecord.project_id == project_id,
                        ReleaseDecisionRecord.version_id == version_id,
                        ReleaseDecisionRecord.us_id == us_id,
                    )
                    .order_by(
                        ReleaseDecisionRecord.created_at.desc(),
                        ReleaseDecisionRecord.id.desc(),
                    )
                    .limit(1)
                )
                if exact is not None:
                    return self._to_release_decision(exact)

            latest = session.scalar(
                select(ReleaseDecisionRecord)
                .where(ReleaseDecisionRecord.project_id == project_id)
                .order_by(
                    ReleaseDecisionRecord.created_at.desc(),
                    ReleaseDecisionRecord.id.desc(),
                )
                .limit(1)
            )
            return (
                self._to_release_decision(latest)
                if latest is not None
                else None
            )

    def load_release_readiness(self) -> dict[str, ReleaseReadiness]:
        with session_scope() as session:
            rows = session.scalars(select(ReleaseReadinessRecord)).all()
        return {row.version_id: self._to_release_readiness(row) for row in rows}

    def get_release_readiness(self, version_id: str) -> ReleaseReadiness | None:
        with session_scope() as session:
            row = session.get(ReleaseReadinessRecord, version_id)
            return self._to_release_readiness(row) if row is not None else None
    def replace_us_items(self, project_id: str, version_id: str | None, items: list[USItem]) -> None:
        with session_scope() as session:
            delete_statement = delete(USWorkItemRecord).where(
                USWorkItemRecord.project_id == project_id
            )
            if version_id is not None:
                delete_statement = delete_statement.where(
                    USWorkItemRecord.version_id == version_id
                )
            session.execute(delete_statement)
            for item in items:
                session.add(
                    USWorkItemRecord(
                        id=item.id,
                        project_id=project_id,
                        version_id=version_id,
                        title=item.title,
                        owner=item.owner,
                        status=item.status,
                        risk=item.risk,
                        progress=item.progress,
                        next_action=item.next_action,
                    )
                )
    def upsert_us_item(self, project_id: str, version_id: str | None, item: USItem) -> None:
        with session_scope() as session:
            row = session.get(USWorkItemRecord, item.id)
            if row is not None and row.project_id != project_id:
                raise ValueError(
                    f"US item {item.id!r} belongs to another project"
                )
            if row is None:
                row = USWorkItemRecord(id=item.id, project_id=project_id, version_id=version_id)
                session.add(row)
            self._assign_us_item(row, project_id, version_id, item)

    def upsert_us_items(
        self,
        project_id: str,
        version_id: str | None,
        items: list[USItem],
    ) -> None:
        with session_scope() as session:
            for item in items:
                row = session.get(USWorkItemRecord, item.id)
                if row is not None and row.project_id != project_id:
                    raise ValueError(
                        f"US item {item.id!r} belongs to another project"
                    )
                if row is None:
                    row = USWorkItemRecord(
                        id=item.id,
                        project_id=project_id,
                        version_id=version_id,
                    )
                    session.add(row)
                self._assign_us_item(row, project_id, version_id, item)

    def upsert_us_item_preserving_version(
        self,
        project_id: str,
        item: USItem,
    ) -> None:
        with session_scope() as session:
            row = session.get(USWorkItemRecord, item.id)
            if row is None or row.project_id != project_id:
                raise ValueError(
                    f"US item {item.id!r} does not belong to project {project_id!r}"
                )
            row.title = item.title
            row.owner = item.owner
            row.status = item.status
            row.risk = item.risk
            row.progress = item.progress
            row.next_action = item.next_action

    def ensure_asset_lanes(
        self,
        project_id: str,
        us_id: str,
        lanes: list[AssetLane],
    ) -> None:
        with session_scope() as session:
            owner = session.scalar(
                select(USWorkItemRecord.project_id).where(
                    USWorkItemRecord.id == us_id
                )
            )
            if owner != project_id:
                raise ValueError(
                    f"US item {us_id!r} does not belong to project {project_id!r}"
                )
            maximum_order = session.scalar(
                select(func.max(AssetLaneRecord.sort_order)).where(
                    AssetLaneRecord.project_id == project_id,
                    AssetLaneRecord.us_id == us_id,
                )
            )
            next_order = (maximum_order + 1) if maximum_order is not None else 0
            for lane in lanes:
                existing = session.get(AssetLaneRecord, lane.id)
                if existing is not None:
                    if existing.project_id != project_id or existing.us_id != us_id:
                        raise ValueError(
                            f"Asset lane {lane.id!r} belongs to another quality scope"
                        )
                    continue
                session.add(
                    self._asset_lane_record(
                        project_id,
                        us_id,
                        lane,
                        next_order,
                    )
                )
                next_order += 1

    def upsert_asset_lane(
        self,
        project_id: str,
        us_id: str,
        lane: AssetLane,
    ) -> None:
        with session_scope() as session:
            owner = session.scalar(
                select(USWorkItemRecord.project_id).where(
                    USWorkItemRecord.id == us_id
                )
            )
            if owner != project_id:
                raise ValueError(
                    f"US item {us_id!r} does not belong to project {project_id!r}"
                )
            row = session.get(AssetLaneRecord, lane.id)
            if row is None:
                maximum_order = session.scalar(
                    select(func.max(AssetLaneRecord.sort_order)).where(
                        AssetLaneRecord.project_id == project_id,
                        AssetLaneRecord.us_id == us_id,
                    )
                )
                row = self._asset_lane_record(
                    project_id,
                    us_id,
                    lane,
                    (maximum_order + 1) if maximum_order is not None else 0,
                )
                session.add(row)
                return
            if row.project_id != project_id or row.us_id != us_id:
                raise ValueError(
                    f"Asset lane {lane.id!r} belongs to another quality scope"
                )
            self._assign_asset_lane(row, lane)
    def replace_asset_lanes(self, project_id: str, us_id: str, lanes: list[AssetLane]) -> None:
        with session_scope() as session:
            session.execute(delete(AssetLaneRecord).where(AssetLaneRecord.us_id == us_id))
            for sort_order, lane in enumerate(lanes):
                session.add(
                    AssetLaneRecord(
                        id=lane.id,
                        project_id=project_id,
                        us_id=us_id,
                        label=lane.label,
                        status=lane.status,
                        summary=lane.summary,
                        updated_at=lane.updated_at,
                        sort_order=sort_order,
                    )
                )
    def replace_runs(self, project_id: str, runs: list[RunDetail]) -> None:
        with session_scope() as session:
            session.execute(delete(RunRecord).where(RunRecord.project_id == project_id))
            for sort_order, run in enumerate(runs):
                session.add(
                    RunRecord(
                        id=run.id,
                        project_id=project_id,
                        status=run.status,
                        channel=run.channel,
                        title=run.title,
                        summary=run.summary,
                        started_at=run.started_at,
                        task_context_id=run.task_context_id,
                        runner_job_id=run.runner_job_id,
                        timeline=run.timeline,
                        evidence=run.evidence,
                        failure_summary=run.failure_summary,
                        healing_status=run.healing_status,
                        healing_depth=run.healing_depth,
                        last_failure_fingerprint=run.last_failure_fingerprint,
                        sort_order=sort_order,
                    )
                )

    def upsert_run_detail(self, project_id: str, run: RunDetail) -> None:
        with session_scope() as session:
            row = session.get(RunRecord, run.id)
            if row is not None and row.project_id != project_id:
                raise ValueError(
                    f"Run {run.id!r} belongs to project {row.project_id!r}, not {project_id!r}"
                )
            if row is None:
                minimum_order = session.scalar(
                    select(func.min(RunRecord.sort_order)).where(
                        RunRecord.project_id == project_id
                    )
                )
                row = RunRecord(
                    id=run.id,
                    project_id=project_id,
                    sort_order=(minimum_order - 1) if minimum_order is not None else 0,
                )
                session.add(row)
            self._assign_run(row, project_id, run)
    def replace_approvals(self, project_id: str, approvals: list[ApprovalDetail]) -> None:
        with session_scope() as session:
            session.execute(delete(ApprovalRecord).where(ApprovalRecord.project_id == project_id))
            for sort_order, approval in enumerate(approvals):
                session.add(
                    ApprovalRecord(
                        id=approval.id,
                        project_id=project_id,
                        title=approval.title,
                        status=approval.status,
                        summary=approval.summary,
                        policy_reason=approval.policy_reason,
                        conflict_fields=approval.conflict_fields,
                        recommended_resolution=approval.recommended_resolution,
                        evidence=approval.evidence,
                        sort_order=sort_order,
                    )
                )
    def upsert_quality_asset_pack(self, pack: QualityAssetPack, sort_order: int = 0) -> None:
        with session_scope() as session:
            row = session.get(QualityAssetPackRecord, pack.id)
            if row is None:
                row = QualityAssetPackRecord(id=pack.id)
                session.add(row)
            row.project_id = pack.project_id
            row.version_id = pack.version_id
            row.us_id = pack.us_id
            row.status = pack.status
            row.current_revision = pack.current_revision
            row.parts = [part.model_dump() for part in pack.parts]
            row.source_refs = pack.source_refs
            row.evidence_refs = pack.evidence_refs
            row.updated_at = pack.updated_at
            row.sort_order = sort_order
    def replace_execution_evidence(self, project_id: str, evidence: list[ExecutionEvidence]) -> None:
        with session_scope() as session:
            session.execute(delete(ExecutionEvidenceRecord).where(ExecutionEvidenceRecord.project_id == project_id))
            for sort_order, item in enumerate(evidence):
                session.add(
                    ExecutionEvidenceRecord(
                        id=item.id,
                        project_id=item.project_id,
                        run_id=item.run_id,
                        us_id=item.us_id,
                        case_ref=item.case_ref,
                        evidence_type=item.evidence_type,
                        storage_ref=item.storage_ref,
                        content_hash=item.content_hash,
                        producer=item.producer,
                        captured_at=item.captured_at,
                        redaction_status=item.redaction_status,
                        retention_policy=item.retention_policy,
                        sort_order=sort_order,
                    )
                )

    def replace_execution_evidence_for_run(
        self,
        project_id: str,
        run_id: str,
        evidence: list[ExecutionEvidence],
    ) -> None:
        for item in evidence:
            if item.project_id != project_id or item.run_id != run_id:
                raise ValueError(
                    "Execution evidence must belong to the requested project and run"
                )
        with session_scope() as session:
            session.execute(
                delete(ExecutionEvidenceRecord).where(
                    ExecutionEvidenceRecord.project_id == project_id,
                    ExecutionEvidenceRecord.run_id == run_id,
                )
            )
            for sort_order, item in enumerate(evidence):
                session.add(self._execution_evidence_record(item, sort_order))
    def replace_failure_reports(self, project_id: str, reports: list[FailureReport]) -> None:
        with session_scope() as session:
            session.execute(delete(FailureReportRecord).where(FailureReportRecord.project_id == project_id))
            for sort_order, item in enumerate(reports):
                session.add(
                    FailureReportRecord(
                        id=item.id,
                        project_id=item.project_id,
                        run_id=item.run_id,
                        us_id=item.us_id,
                        failure_kind=item.failure_kind,
                        failure_fingerprint=item.failure_fingerprint,
                        summary=item.summary,
                        root_cause=item.root_cause,
                        evidence_refs=item.evidence_refs,
                        status=item.status,
                        healing_attempt_count=item.healing_attempt_count,
                        fallback_to_human=item.fallback_to_human,
                        cooldown_until=item.cooldown_until,
                        created_at=item.created_at,
                        sort_order=sort_order,
                    )
                )

    def replace_failure_analysis(
        self,
        project_id: str,
        runs: list[RunDetail],
        reports: list[FailureReport],
    ) -> None:
        """Atomically replace failed-run and FailureReport facts."""

        with session_scope() as session:
            session.execute(delete(RunRecord).where(RunRecord.project_id == project_id))
            for sort_order, run in enumerate(runs):
                session.add(
                    RunRecord(
                        id=run.id,
                        project_id=project_id,
                        status=run.status,
                        channel=run.channel,
                        title=run.title,
                        summary=run.summary,
                        started_at=run.started_at,
                        task_context_id=run.task_context_id,
                        runner_job_id=run.runner_job_id,
                        timeline=run.timeline,
                        evidence=run.evidence,
                        failure_summary=run.failure_summary,
                        healing_status=run.healing_status,
                        healing_depth=run.healing_depth,
                        last_failure_fingerprint=run.last_failure_fingerprint,
                        sort_order=sort_order,
                    )
                )
            session.execute(
                delete(FailureReportRecord).where(
                    FailureReportRecord.project_id == project_id
                )
            )
            for sort_order, report in enumerate(reports):
                row = FailureReportRecord(
                    id=report.id,
                    project_id=report.project_id,
                    sort_order=sort_order,
                )
                self._assign_failure_report(row, report)
                session.add(row)

    def upsert_failure_analysis(
        self,
        project_id: str,
        run: RunDetail,
        reports: list[FailureReport],
    ) -> None:
        """Persist one failed run and its reports without replacing peer facts."""

        for report in reports:
            if report.project_id != project_id:
                raise ValueError(
                    f"Failure report {report.id!r} does not belong to {project_id!r}"
                )
        with session_scope() as session:
            run_row = session.get(RunRecord, run.id)
            if run_row is not None and run_row.project_id != project_id:
                raise ValueError(
                    f"Run {run.id!r} belongs to project {run_row.project_id!r}, not {project_id!r}"
                )
            if run_row is None:
                minimum_order = session.scalar(
                    select(func.min(RunRecord.sort_order)).where(
                        RunRecord.project_id == project_id
                    )
                )
                run_row = RunRecord(
                    id=run.id,
                    project_id=project_id,
                    sort_order=(minimum_order - 1) if minimum_order is not None else 0,
                )
                session.add(run_row)
            self._assign_run(run_row, project_id, run)

            minimum_report_order = session.scalar(
                select(func.min(FailureReportRecord.sort_order)).where(
                    FailureReportRecord.project_id == project_id
                )
            )
            next_order = (
                minimum_report_order - 1
                if minimum_report_order is not None
                else 0
            )
            for report in reports:
                row = session.get(FailureReportRecord, report.id)
                if row is not None and row.project_id != project_id:
                    raise ValueError(
                        f"Failure report {report.id!r} belongs to another project"
                    )
                if row is None:
                    row = FailureReportRecord(
                        id=report.id,
                        project_id=project_id,
                        sort_order=next_order,
                    )
                    next_order -= 1
                    session.add(row)
                self._assign_failure_report(row, report)

    def upsert_release_decision(self, decision: ReleaseDecision) -> None:
        with session_scope() as session:
            row = session.get(ReleaseDecisionRecord, decision.id)
            if row is None:
                row = ReleaseDecisionRecord(id=decision.id)
                session.add(row)
            row.project_id = decision.project_id
            row.version_id = decision.version_id
            row.us_id = decision.us_id
            row.status = decision.status
            row.score = decision.score
            row.rationale = decision.rationale
            row.evidence_refs = decision.evidence_refs
            row.approval_ref = decision.approval_ref
            row.created_at = decision.created_at

    def upsert_merged_resolution(self, resolution: MergedResolution) -> None:
        with session_scope() as session:
            row = session.get(MergedResolutionRecord, resolution.id)
            if row is None:
                row = MergedResolutionRecord(id=resolution.id)
                session.add(row)
            row.project_id = resolution.project_id
            row.version_id = resolution.version_id
            row.task_id = resolution.task_id
            row.object_ref = resolution.object_ref
            row.resolution_kind = resolution.resolution_kind
            row.status = resolution.status
            row.base_ref = resolution.base_ref
            row.left_candidate_ref = resolution.left_candidate_ref
            row.right_candidate_ref = resolution.right_candidate_ref
            row.base_value = resolution.base_value
            row.left_candidate = resolution.left_candidate
            row.right_candidate = resolution.right_candidate
            row.merged_value = resolution.merged_value
            row.auto_merged_patch = resolution.auto_merged_patch
            row.conflict_entries = [
                item.model_dump(mode="json") for item in resolution.conflict_entries
            ]
            row.recommended_resolution = resolution.recommended_resolution
            row.merged_from = resolution.merged_from
            row.approval_state = resolution.approval_state
            row.approval_ref = resolution.approval_ref
            row.evidence_refs = resolution.evidence_refs
            row.created_at = resolution.created_at
            row.updated_at = resolution.updated_at
    def upsert_release_readiness(self, project_id: str, readiness: ReleaseReadiness) -> None:
        with session_scope() as session:
            row = session.get(ReleaseReadinessRecord, readiness.version_id)
            if row is None:
                row = ReleaseReadinessRecord(version_id=readiness.version_id, project_id=project_id)
                session.add(row)
            row.project_id = project_id
            row.status = readiness.status
            row.score = readiness.score
            row.blockers = readiness.blockers
            row.approvals_open = readiness.approvals_open
            row.pending_merge = readiness.pending_merge
            row.execution_health = readiness.execution_health
            row.summary = readiness.summary
            row.blocker_items = readiness.blocker_items
            row.score_breakdown = readiness.score_breakdown
            row.evidence_summary = readiness.evidence_summary

    @staticmethod
    def _assign_us_item(
        row: USWorkItemRecord,
        project_id: str,
        version_id: str | None,
        item: USItem,
    ) -> None:
        row.project_id = project_id
        row.version_id = version_id
        row.title = item.title
        row.owner = item.owner
        row.status = item.status
        row.risk = item.risk
        row.progress = item.progress
        row.next_action = item.next_action

    @staticmethod
    def _asset_lane_record(
        project_id: str,
        us_id: str,
        lane: AssetLane,
        sort_order: int,
    ) -> AssetLaneRecord:
        row = AssetLaneRecord(
            id=lane.id,
            project_id=project_id,
            us_id=us_id,
            sort_order=sort_order,
        )
        QualityLoopRepository._assign_asset_lane(row, lane)
        return row

    @staticmethod
    def _assign_asset_lane(row: AssetLaneRecord, lane: AssetLane) -> None:
        row.label = lane.label
        row.status = lane.status
        row.summary = lane.summary
        row.updated_at = lane.updated_at

    @staticmethod
    def _assign_run(row: RunRecord, project_id: str, run: RunDetail) -> None:
        row.project_id = project_id
        row.status = run.status
        row.channel = run.channel
        row.title = run.title
        row.summary = run.summary
        row.started_at = run.started_at
        row.task_context_id = run.task_context_id
        row.runner_job_id = run.runner_job_id
        row.timeline = list(run.timeline)
        row.evidence = list(run.evidence)
        row.failure_summary = run.failure_summary
        row.healing_status = run.healing_status
        row.healing_depth = run.healing_depth
        row.last_failure_fingerprint = run.last_failure_fingerprint
        row.us_id = run.us_id
        row.target_base_url = run.target_base_url
        row.automation_asset_ref = run.automation_asset_ref
        row.automation_script_id = run.automation_script_id
        row.execution_plan = list(run.execution_plan)
        row.execution_timeout_ms = run.execution_timeout_ms
        row.retry_of_run_id = run.retry_of_run_id
        row.attempt = run.attempt

    @staticmethod
    def _execution_evidence_record(
        item: ExecutionEvidence,
        sort_order: int,
    ) -> ExecutionEvidenceRecord:
        return ExecutionEvidenceRecord(
            id=item.id,
            project_id=item.project_id,
            run_id=item.run_id,
            us_id=item.us_id,
            case_ref=item.case_ref,
            evidence_type=item.evidence_type,
            storage_ref=item.storage_ref,
            content_hash=item.content_hash,
            producer=item.producer,
            captured_at=item.captured_at,
            redaction_status=item.redaction_status,
            retention_policy=item.retention_policy,
            sort_order=sort_order,
        )

    @staticmethod
    def _assign_failure_report(
        row: FailureReportRecord,
        item: FailureReport,
    ) -> None:
        row.project_id = item.project_id
        row.run_id = item.run_id
        row.us_id = item.us_id
        row.failure_kind = item.failure_kind
        row.failure_fingerprint = item.failure_fingerprint
        row.summary = item.summary
        row.root_cause = item.root_cause
        row.evidence_refs = list(item.evidence_refs)
        row.status = item.status
        row.healing_attempt_count = item.healing_attempt_count
        row.fallback_to_human = item.fallback_to_human
        row.cooldown_until = item.cooldown_until
        row.created_at = item.created_at

    @staticmethod
    def _to_us_item(row: USWorkItemRecord) -> USItem:
        return USItem(
            id=row.id,
            title=row.title,
            owner=row.owner,
            status=row.status,
            risk=row.risk,
            progress=row.progress,
            next_action=row.next_action,
        )
    @staticmethod
    def _to_asset_lane(row: AssetLaneRecord) -> AssetLane:
        return AssetLane(
            id=row.id,
            label=row.label,
            status=row.status,
            summary=row.summary,
            updated_at=row.updated_at,
        )
    @staticmethod
    def _to_run_summary(row: RunRecord) -> RunSummary:
        return RunSummary(
            id=row.id,
            status=row.status,
            channel=row.channel,  # type: ignore[arg-type]
            title=row.title,
            summary=row.summary,
            started_at=row.started_at,
        )
    @staticmethod
    def _to_run_detail(row: RunRecord) -> RunDetail:
        return RunDetail(
            id=row.id,
            status=row.status,
            channel=row.channel,  # type: ignore[arg-type]
            title=row.title,
            summary=row.summary,
            started_at=row.started_at,
            task_context_id=row.task_context_id,
            runner_job_id=row.runner_job_id,
            timeline=row.timeline or [],
            evidence=row.evidence or [],
            failure_summary=row.failure_summary,
            healing_status=row.healing_status,
            healing_depth=row.healing_depth,
            last_failure_fingerprint=row.last_failure_fingerprint,
            us_id=row.us_id,
            target_base_url=row.target_base_url,
            automation_asset_ref=row.automation_asset_ref,
            automation_script_id=row.automation_script_id,
            execution_plan=row.execution_plan or [],
            execution_timeout_ms=row.execution_timeout_ms or 60_000,
            retry_of_run_id=row.retry_of_run_id,
            attempt=row.attempt or 1,
        )
    @staticmethod
    def _to_approval_summary(row: ApprovalRecord) -> ApprovalSummary:
        return ApprovalSummary(
            id=row.id,
            title=row.title,
            status=row.status,
            summary=row.summary,
        )
    @staticmethod
    def _to_approval_detail(row: ApprovalRecord) -> ApprovalDetail:
        return ApprovalDetail(
            id=row.id,
            title=row.title,
            status=row.status,
            summary=row.summary,
            policy_reason=row.policy_reason,
            conflict_fields=row.conflict_fields or [],
            recommended_resolution=row.recommended_resolution,
            evidence=row.evidence or [],
        )

    @staticmethod
    def _to_merged_resolution(row: MergedResolutionRecord) -> MergedResolution:
        return MergedResolution(
            id=row.id,
            project_id=row.project_id,
            version_id=row.version_id,
            task_id=row.task_id,
            object_ref=row.object_ref,
            resolution_kind=row.resolution_kind,
            status=row.status,
            base_ref=row.base_ref,
            left_candidate_ref=row.left_candidate_ref,
            right_candidate_ref=row.right_candidate_ref,
            base_value=row.base_value,
            left_candidate=row.left_candidate,
            right_candidate=row.right_candidate,
            merged_value=row.merged_value,
            auto_merged_patch=row.auto_merged_patch or [],
            conflict_entries=[
                ConflictEntry(**item) for item in (row.conflict_entries or [])
            ],
            recommended_resolution=row.recommended_resolution,
            merged_from=row.merged_from or [],
            approval_state=row.approval_state,
            approval_ref=row.approval_ref,
            evidence_refs=row.evidence_refs or [],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    @staticmethod
    def _to_quality_asset_pack(row: QualityAssetPackRecord) -> QualityAssetPack:
        return QualityAssetPack(
            id=row.id,
            project_id=row.project_id,
            version_id=row.version_id,
            us_id=row.us_id,
            status=row.status,  # type: ignore[arg-type]
            current_revision=row.current_revision,
            parts=[QualityAssetPart(**part) for part in (row.parts or [])],
            source_refs=row.source_refs or [],
            evidence_refs=row.evidence_refs or [],
            updated_at=row.updated_at,
        )
    @staticmethod
    def _to_execution_evidence(row: ExecutionEvidenceRecord) -> ExecutionEvidence:
        return ExecutionEvidence(
            id=row.id,
            project_id=row.project_id,
            run_id=row.run_id,
            us_id=row.us_id,
            case_ref=row.case_ref,
            evidence_type=row.evidence_type,  # type: ignore[arg-type]
            storage_ref=row.storage_ref,
            content_hash=row.content_hash,
            producer=row.producer,  # type: ignore[arg-type]
            captured_at=row.captured_at,
            redaction_status=row.redaction_status,  # type: ignore[arg-type]
            retention_policy=row.retention_policy,
        )
    @staticmethod
    def _to_failure_report(row: FailureReportRecord) -> FailureReport:
        return FailureReport(
            id=row.id,
            project_id=row.project_id,
            run_id=row.run_id,
            us_id=row.us_id,
            failure_kind=row.failure_kind,  # type: ignore[arg-type]
            failure_fingerprint=row.failure_fingerprint,
            summary=row.summary,
            root_cause=row.root_cause,
            evidence_refs=row.evidence_refs or [],
            status=row.status,  # type: ignore[arg-type]
            healing_attempt_count=row.healing_attempt_count,
            fallback_to_human=row.fallback_to_human,
            cooldown_until=row.cooldown_until,
            created_at=row.created_at,
        )
    @staticmethod
    def _to_release_decision(row: ReleaseDecisionRecord) -> ReleaseDecision:
        return ReleaseDecision(
            id=row.id,
            project_id=row.project_id,
            version_id=row.version_id,
            us_id=row.us_id,
            status=row.status,  # type: ignore[arg-type]
            score=row.score,
            rationale=row.rationale,
            evidence_refs=row.evidence_refs or [],
            approval_ref=row.approval_ref,
            created_at=row.created_at,
        )
    @staticmethod
    def _to_release_readiness(row: ReleaseReadinessRecord) -> ReleaseReadiness:
        return ReleaseReadiness(
            version_id=row.version_id,
            status=row.status,
            score=row.score,
            blockers=row.blockers,
            approvals_open=row.approvals_open,
            pending_merge=row.pending_merge,
            execution_health=row.execution_health,
            summary=row.summary,
            blocker_items=row.blocker_items or [],
            score_breakdown=row.score_breakdown or {},
            evidence_summary=row.evidence_summary or {},
        )
