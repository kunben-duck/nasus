from __future__ import annotations

from datetime import datetime, timezone

from .ports import QualityExecutionEvidenceReadPort, QualityFailureWorkspacePort
from .quality_models import FailureReport, RunDetail
from .runner_port import QualityAutomationExecutionPort
from ...domain.quality_loop.failure_analysis import decide_failure_report, identify_failure


class QualityFailureReportApplicationService:
    """Write-side boundary for failure analysis facts and run healing state."""

    def __init__(
        self,
        workspace: QualityFailureWorkspacePort,
        evidence: QualityExecutionEvidenceReadPort,
        evidence_materializer: QualityAutomationExecutionPort,
        *,
        max_healing_depth: int,
    ) -> None:
        self._workspace = workspace
        self._evidence = evidence
        self._evidence_materializer = evidence_materializer
        self.max_healing_depth = max_healing_depth

    def upsert_failure_report(
        self,
        project_id: str,
        us_id: str,
        run: RunDetail,
        *,
        increment_healing_attempt: bool,
    ) -> FailureReport:
        updated_run = run.model_copy(deep=True)
        existing_evidence = [
            item
            for item in self._evidence.list_execution_evidence(project_id)
            if item.run_id == run.id
        ]
        if not existing_evidence:
            existing_evidence = self._evidence_materializer.materialize_evidence(
                project_id,
                us_id,
                updated_run,
            )
        updated_run.evidence = [item.storage_ref for item in existing_evidence]
        evidence_refs = [f"execution_evidence:{item.id}" for item in existing_evidence]
        identity = identify_failure(project_id, us_id, updated_run)
        existing_reports = self._workspace.list_failure_reports(project_id)
        existing_report = next(
            (
                item
                for item in existing_reports
                if item.id == identity.report_id
            ),
            None,
        )
        decision = decide_failure_report(
            project_id,
            us_id,
            updated_run,
            existing_healing_attempt_count=existing_report.healing_attempt_count if existing_report else 0,
            increment_healing_attempt=increment_healing_attempt,
            max_healing_depth=self.max_healing_depth,
        )
        now = self._now()
        report = FailureReport(
            id=decision.identity.report_id,
            project_id=project_id,
            run_id=run.id,
            us_id=us_id,
            failure_kind=decision.failure_kind,
            failure_fingerprint=decision.identity.fingerprint,
            summary=decision.summary,
            root_cause=decision.root_cause,
            evidence_refs=evidence_refs,
            status=decision.status,  # type: ignore[arg-type]
            healing_attempt_count=decision.healing_attempt_count,
            fallback_to_human=decision.fallback_to_human,
            cooldown_until=now if decision.fallback_to_human else None,
            created_at=existing_report.created_at if existing_report else now,
        )
        reports = [
            report,
            *[
                item
                for item in existing_reports
                if item.id != report.id
            ],
        ]
        updated_run.healing_status = decision.run_healing_status
        updated_run.healing_depth = decision.healing_attempt_count
        updated_run.last_failure_fingerprint = decision.identity.fingerprint
        updated_run.failure_summary = report.summary
        self._workspace.save_failure_analysis(
            project_id,
            updated_run,
            reports,
        )
        run.evidence = list(updated_run.evidence)
        run.healing_status = updated_run.healing_status
        run.healing_depth = updated_run.healing_depth
        run.last_failure_fingerprint = updated_run.last_failure_fingerprint
        run.failure_summary = updated_run.failure_summary
        return report

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


__all__ = ["QualityFailureReportApplicationService"]
