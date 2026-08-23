from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import select

from .database import SessionLocal
from .db_models import (
    ApprovalRecord,
    ExecutionEvidenceRecord,
    FailureReportRecord,
    ProjectRecord,
    QualityAssetPackRecord,
    QualityProfileRecord,
    ReleaseReadinessRecord,
    RunRecord,
    TaskContextRecord,
    USWorkItemRecord,
)
from ...application.quality_loop.quality_models import ReleaseReadiness
from ...application.quality_loop.release_readiness_port import (
    ReleaseFailureFact,
    ReleaseReadinessSnapshot,
)


class SQLAlchemyReleaseReadinessRepository:
    """SQLAlchemy adapter for authoritative release-readiness facts."""

    def __init__(self, session_factory: Any = SessionLocal) -> None:
        self._session_factory = session_factory

    @contextmanager
    def _session_scope(self) -> Iterator[Any]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def load_snapshot(
        self,
        *,
        project_id: str,
        us_id: str,
        version_id: str,
    ) -> ReleaseReadinessSnapshot:
        with self._session_scope() as session:
            failure_rows = session.scalars(
                select(FailureReportRecord)
                .where(
                    FailureReportRecord.project_id == project_id,
                    FailureReportRecord.us_id == us_id,
                    ~FailureReportRecord.status.in_(("resolved", "closed")),
                )
                .order_by(FailureReportRecord.sort_order)
            ).all()
            evidence_rows = session.scalars(
                select(ExecutionEvidenceRecord)
                .where(
                    ExecutionEvidenceRecord.project_id == project_id,
                    ExecutionEvidenceRecord.us_id == us_id,
                )
                .order_by(ExecutionEvidenceRecord.sort_order)
            ).all()
            related_run_ids = {
                row.run_id for row in evidence_rows
            } | {
                row.run_id for row in failure_rows
            }
            run_query = (
                select(RunRecord)
                .where(RunRecord.project_id == project_id)
                .order_by(RunRecord.sort_order)
            )
            if related_run_ids:
                run_rows = session.scalars(
                    run_query.where(RunRecord.id.in_(related_run_ids))
                ).all()
            else:
                us_ids = session.scalars(
                    select(USWorkItemRecord.id).where(
                        USWorkItemRecord.project_id == project_id
                    )
                ).all()
                run_rows = session.scalars(run_query).all() if len(us_ids) == 1 else []

            pack = session.scalars(
                select(QualityAssetPackRecord)
                .where(
                    QualityAssetPackRecord.project_id == project_id,
                    QualityAssetPackRecord.us_id == us_id,
                )
                .order_by(QualityAssetPackRecord.sort_order)
                .limit(1)
            ).first()
            task_context = session.scalars(
                select(TaskContextRecord)
                .where(
                    TaskContextRecord.project_id == project_id,
                    TaskContextRecord.us_id == us_id,
                )
                .order_by(TaskContextRecord.sort_order)
                .limit(1)
            ).first()
            quality_profile = session.scalars(
                select(QualityProfileRecord)
                .where(
                    QualityProfileRecord.project_id == project_id,
                    QualityProfileRecord.us_id == us_id,
                )
                .order_by(QualityProfileRecord.sort_order)
                .limit(1)
            ).first()
            approval_rows = session.scalars(
                select(ApprovalRecord).where(
                    ApprovalRecord.project_id == project_id,
                    ApprovalRecord.status.in_(
                        ("waiting_approval", "pending", "requested", "open", "under_review")
                    ),
                )
            ).all()
            previous = session.get(ReleaseReadinessRecord, version_id)

            parts = pack.parts if pack is not None and isinstance(pack.parts, list) else []
            asset_part_statuses = tuple(
                (str(part.get("part_type", "")), str(part.get("status", "")))
                for part in parts
                if isinstance(part, dict)
            )
            fallback_generated_parts = sum(
                1
                for part in parts
                if isinstance(part, dict)
                and isinstance(part.get("generation"), dict)
                and part["generation"].get("mode") == "fallback"
            )
            pending_merge = max(
                1 if pack is not None and pack.status == "pending_merge" else 0,
                previous.pending_merge if previous is not None else 0,
            )

            return ReleaseReadinessSnapshot(
                version_id=version_id,
                run_statuses=tuple(row.status for row in run_rows),
                evidence_types=tuple(row.evidence_type for row in evidence_rows),
                asset_part_statuses=asset_part_statuses,
                task_context_readiness=task_context.readiness if task_context is not None else None,
                task_context_confidence=task_context.confidence if task_context is not None else 0,
                missing_context_count=(
                    len(task_context.missing_context or []) if task_context is not None else 0
                ),
                quality_profile_coverage=(
                    quality_profile.coverage_score if quality_profile is not None else 0
                ),
                quality_profile_confidence=(
                    quality_profile.confidence if quality_profile is not None else 0
                ),
                fallback_generated_parts=fallback_generated_parts,
                open_failures=tuple(
                    ReleaseFailureFact(
                        failure_kind=row.failure_kind,
                        summary=row.summary,
                        fallback_to_human=row.fallback_to_human,
                    )
                    for row in failure_rows
                ),
                approvals_open=len(approval_rows),
                pending_merge=pending_merge,
            )

    def save_assessment(
        self,
        *,
        project_id: str,
        readiness: ReleaseReadiness,
        progress_floor: int,
        blockers: int,
    ) -> None:
        with self._session_scope() as session:
            row = session.get(ReleaseReadinessRecord, readiness.version_id)
            if row is None:
                row = ReleaseReadinessRecord(
                    version_id=readiness.version_id,
                    project_id=project_id,
                )
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

            project = session.get(ProjectRecord, project_id)
            if project is None:
                raise ValueError(f"Project {project_id} does not exist")
            project.progress = max(project.progress, progress_floor)
            project.blocked_items = max(project.blocked_items, blockers)
            project.risk = "low" if project.blocked_items == 0 else "high"


__all__ = ["SQLAlchemyReleaseReadinessRepository"]
