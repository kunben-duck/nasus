from __future__ import annotations

from threading import RLock
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.failure_reports import (
    QualityFailureReportApplicationService,
)
from apps.api.app.application.quality_loop.quality_models import (
    ExecutionEvidence,
    FailureReport,
    RunDetail,
)
from apps.api.app.infrastructure.quality_loop import LegacyQualityFailureWorkspace


def failed_run() -> RunDetail:
    return RunDetail(
        id="run_failure",
        status="failed",
        channel="web_runner",
        title="Checkout validation",
        summary="Checkout assertion failed.",
        started_at="2026-07-30T00:00:00Z",
        failure_summary="Selector assertion failed on the payment button.",
        healing_status="not_started",
    )


def failure_evidence() -> ExecutionEvidence:
    return ExecutionEvidence(
        id="evidence_failure",
        project_id="project_failure",
        run_id="run_failure",
        us_id="us_failure",
        evidence_type="failure_artifact",
        storage_ref="s3://nasus-artifacts/failures/run_failure.json",
        content_hash="sha256:failure",
        producer="web_runner",
        captured_at="2026-07-30T00:00:01Z",
    )


class RecordingFailureWorkspace:
    def __init__(self) -> None:
        self.reports: list[FailureReport] = []
        self.saved_run: RunDetail | None = None
        self.fail_save = False

    def list_failure_reports(self, project_id: str) -> list[FailureReport]:
        return [item.model_copy(deep=True) for item in self.reports]

    def save_failure_analysis(
        self,
        project_id: str,
        run: RunDetail,
        reports: list[FailureReport],
    ) -> None:
        if self.fail_save:
            raise RuntimeError("transaction failed")
        self.saved_run = run.model_copy(deep=True)
        self.reports = [item.model_copy(deep=True) for item in reports]


class RecordingEvidenceReader:
    def __init__(self, evidence: list[ExecutionEvidence]) -> None:
        self.evidence = evidence

    def list_execution_evidence(self, project_id: str) -> list[ExecutionEvidence]:
        return [item.model_copy(deep=True) for item in self.evidence]


class RecordingEvidenceMaterializer:
    def __init__(self, evidence: list[ExecutionEvidence]) -> None:
        self.evidence = evidence
        self.calls = 0

    def materialize_evidence(
        self,
        project_id: str,
        us_id: str,
        run: RunDetail,
    ) -> list[ExecutionEvidence]:
        self.calls += 1
        return [item.model_copy(deep=True) for item in self.evidence]


def test_failure_analysis_uses_persisted_evidence_and_saves_detached_run() -> None:
    evidence = failure_evidence()
    workspace = RecordingFailureWorkspace()
    materializer = RecordingEvidenceMaterializer([evidence])
    service = QualityFailureReportApplicationService(
        workspace,
        RecordingEvidenceReader([evidence]),
        materializer,
        max_healing_depth=2,
    )
    run = failed_run()

    report = service.upsert_failure_report(
        "project_failure",
        "us_failure",
        run,
        increment_healing_attempt=False,
    )

    assert materializer.calls == 0
    assert report.status == "under_review"
    assert report.failure_kind == "selector"
    assert report.evidence_refs == [f"execution_evidence:{evidence.id}"]
    assert workspace.saved_run is not None
    assert workspace.saved_run.evidence == [evidence.storage_ref]
    assert workspace.saved_run is not run
    assert run.evidence == [evidence.storage_ref]
    assert run.last_failure_fingerprint == report.failure_fingerprint


def test_failure_analysis_materializes_missing_evidence() -> None:
    evidence = failure_evidence()
    workspace = RecordingFailureWorkspace()
    materializer = RecordingEvidenceMaterializer([evidence])
    service = QualityFailureReportApplicationService(
        workspace,
        RecordingEvidenceReader([]),
        materializer,
        max_healing_depth=2,
    )

    report = service.upsert_failure_report(
        "project_failure",
        "us_failure",
        failed_run(),
        increment_healing_attempt=False,
    )

    assert materializer.calls == 1
    assert report.evidence_refs == [f"execution_evidence:{evidence.id}"]
    assert workspace.saved_run is not None
    assert workspace.saved_run.evidence == [evidence.storage_ref]


def test_repeated_failure_falls_back_to_human_at_healing_limit() -> None:
    evidence = failure_evidence()
    workspace = RecordingFailureWorkspace()
    service = QualityFailureReportApplicationService(
        workspace,
        RecordingEvidenceReader([evidence]),
        RecordingEvidenceMaterializer([evidence]),
        max_healing_depth=2,
    )

    first = service.upsert_failure_report(
        "project_failure",
        "us_failure",
        failed_run(),
        increment_healing_attempt=True,
    )
    second_run = failed_run()
    second = service.upsert_failure_report(
        "project_failure",
        "us_failure",
        second_run,
        increment_healing_attempt=True,
    )

    assert first.status == "healing_proposed"
    assert first.healing_attempt_count == 1
    assert second.status == "fallback_to_human"
    assert second.healing_attempt_count == 2
    assert second.fallback_to_human is True
    assert second_run.healing_status == "fallback_to_human"


def test_failed_persistence_does_not_mutate_caller_run() -> None:
    evidence = failure_evidence()
    workspace = RecordingFailureWorkspace()
    workspace.fail_save = True
    service = QualityFailureReportApplicationService(
        workspace,
        RecordingEvidenceReader([evidence]),
        RecordingEvidenceMaterializer([evidence]),
        max_healing_depth=2,
    )
    run = failed_run()
    original = run.model_copy(deep=True)

    with pytest.raises(RuntimeError, match="transaction failed"):
        service.upsert_failure_report(
            "project_failure",
            "us_failure",
            run,
            increment_healing_attempt=True,
        )

    assert run == original


class RecordingAtomicQualityLoopRepository:
    def __init__(self, reports: list[FailureReport]) -> None:
        self.reports = reports
        self.atomic_calls: list[tuple[str, list[RunDetail], list[FailureReport]]] = []

    def list_failure_reports(self, project_id: str) -> list[FailureReport]:
        return [item.model_copy(deep=True) for item in self.reports]

    def replace_failure_analysis(
        self,
        project_id: str,
        runs: list[RunDetail],
        reports: list[FailureReport],
    ) -> None:
        self.atomic_calls.append(
            (
                project_id,
                [item.model_copy(deep=True) for item in runs],
                [item.model_copy(deep=True) for item in reports],
            )
        )


def test_legacy_failure_workspace_uses_atomic_repository_boundary() -> None:
    report = FailureReport(
        id="failure_run_failure",
        project_id="project_failure",
        run_id="run_failure",
        us_id="us_failure",
        failure_kind="selector",
        failure_fingerprint="fingerprint",
        summary="Selector failed.",
        root_cause="Selector drift.",
        status="under_review",
        created_at="2026-07-30T00:00:02Z",
    )
    repository = RecordingAtomicQualityLoopRepository([report])
    projection_lock = RLock()
    state = SimpleNamespace(
        failure_reports={"project_failure": []},
        run_details={},
        runs={"project_failure": []},
    )
    adapters = SimpleNamespace(
        mutation_guard=lambda: projection_lock,
        quality_loop_repository=repository,
    )
    workspace = LegacyQualityFailureWorkspace(state, adapters)

    loaded = workspace.list_failure_reports("project_failure")
    run = failed_run()
    workspace.save_failure_analysis("project_failure", run, loaded)

    assert repository.atomic_calls[0][0] == "project_failure"
    assert repository.atomic_calls[0][1][0].id == run.id
    assert repository.atomic_calls[0][2][0].id == report.id
    assert state.run_details[run.id] is not run
    assert state.failure_reports["project_failure"][0] is not loaded[0]
