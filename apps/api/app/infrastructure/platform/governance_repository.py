from __future__ import annotations

from sqlalchemy import func, select

from ...application.quality_loop.quality_models import ApprovalDetail
from ..persistence.db_models import ApprovalRecord, ProjectRecord, VersionRecord
from ..persistence.unit_of_work import session_scope


class SQLAlchemyGovernanceCommandRepository:
    """Atomic governance writes spanning approval and derived project facts."""

    def save_approval_and_sync_pending_counts(
        self,
        project_id: str,
        approval: ApprovalDetail,
    ) -> int:
        with session_scope() as session:
            project = session.get(ProjectRecord, project_id)
            if project is None:
                raise KeyError(project_id)

            row = session.get(ApprovalRecord, approval.id)
            if row is not None and row.project_id != project_id:
                raise ValueError(
                    f"Approval {approval.id!r} belongs to another project"
                )
            if row is None:
                maximum_order = session.scalar(
                    select(func.max(ApprovalRecord.sort_order)).where(
                        ApprovalRecord.project_id == project_id
                    )
                )
                row = ApprovalRecord(
                    id=approval.id,
                    project_id=project_id,
                    sort_order=(maximum_order + 1) if maximum_order is not None else 0,
                )
                session.add(row)

            row.title = approval.title
            row.status = approval.status
            row.summary = approval.summary
            row.policy_reason = approval.policy_reason
            row.conflict_fields = approval.conflict_fields
            row.recommended_resolution = approval.recommended_resolution
            row.evidence = approval.evidence
            session.flush()

            pending = int(
                session.scalar(
                    select(func.count(ApprovalRecord.id)).where(
                        ApprovalRecord.project_id == project_id,
                        ApprovalRecord.status == "waiting_approval",
                    )
                )
                or 0
            )
            project.pending_approvals = pending
            first_version = session.scalar(
                select(VersionRecord)
                .where(VersionRecord.project_id == project_id)
                .order_by(VersionRecord.sort_order, VersionRecord.id)
                .limit(1)
            )
            if first_version is not None:
                first_version.pending_approvals = pending
            return pending


__all__ = ["SQLAlchemyGovernanceCommandRepository"]
