from __future__ import annotations

import base64
from pathlib import Path
from threading import RLock
from types import SimpleNamespace

import httpx

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.quality_models import (
    ExecutionEvidence,
    RunDetail,
    USItem,
)
from apps.api.app.application.quality_loop.runner_port import AutomationRunnerCommand
from apps.api.app.infrastructure.quality_loop import LegacyQualityRunWorkspace
from apps.api.app.infrastructure.runner.adapters import HttpAutomationRunner
from apps.api.app.infrastructure.runner.run_orchestrator import RunOrchestrator
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig


class RecordingQualityLoopRepository:
    def __init__(self) -> None:
        self.runs = []
        self.evidence = []

    def replace_runs(self, project_id, runs) -> None:
        self.runs = list(runs)

    def replace_execution_evidence(self, project_id, evidence) -> None:
        self.evidence = list(evidence)


class RecordingRunWorkspace:
    def __init__(self) -> None:
        self.us_titles = {}
        self.runs = []
        self.evidence = []

    def us_title(self, project_id: str, us_id: str) -> str | None:
        return self.us_titles.get((project_id, us_id))

    def save_run_detail(self, project_id: str, run: RunDetail) -> None:
        self.runs = [run.model_copy(deep=True), *[item for item in self.runs if item.id != run.id]]

    def replace_run_evidence(
        self,
        project_id: str,
        run_id: str,
        evidence: list[ExecutionEvidence],
    ) -> None:
        self.evidence = [
            *[item.model_copy(deep=True) for item in evidence],
            *[item for item in self.evidence if item.run_id != run_id],
        ]


class EmptyTaskContextProvider:
    def current_task_context(self, project_id: str, us_id: str | None = None):
        return None


def runner_dependencies(tmp_path: Path):
    workspace = RecordingRunWorkspace()
    storage = ObjectStorage(
        ObjectStorageConfig(
            endpoint=None,
            bucket="runner-tests",
            access_key=None,
            secret_key=None,
            region="us-east-1",
            local_dir=tmp_path,
        )
    )
    return workspace, storage


def test_runner_unavailable_fails_closed_and_persists_failure_evidence(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("NASUS_RUNNER_MODE", "unavailable")
    workspace, storage = runner_dependencies(tmp_path)
    orchestrator = RunOrchestrator(
        workspace,
        EmptyTaskContextProvider(),
        storage,
    )

    outcome = orchestrator.execute_automation(
        "proj_runner",
        "us_runner",
        invocation_input={
            "runner_result": {"status": "passed"},
            "runner_request": {
                "base_url": "https://example.com",
                "steps": [{"action": "goto", "path": "/"}],
            },
        },
    )

    assert outcome.failed is True
    assert outcome.run.status == "failed"
    assert outcome.runner_mode == "unavailable"
    assert outcome.run.us_id == "us_runner"
    assert outcome.run.target_base_url == "https://example.com"
    assert outcome.run.execution_plan == [{"action": "goto", "path": "/"}]
    assert outcome.run.execution_timeout_ms == 60_000
    assert outcome.run.attempt == 1
    assert {item.evidence_type for item in outcome.evidence} == {"report", "failure_artifact"}
    assert workspace.runs[0].status == "failed"
    assert {item.id for item in workspace.evidence} == {item.id for item in outcome.evidence}
    assert all(storage.get_bytes(item.storage_ref) for item in outcome.evidence)


def test_protocol_stub_is_available_only_when_explicitly_selected(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("NASUS_RUNNER_MODE", "protocol_stub")
    workspace, storage = runner_dependencies(tmp_path)
    orchestrator = RunOrchestrator(
        workspace,
        EmptyTaskContextProvider(),
        storage,
    )

    outcome = orchestrator.execute_automation(
        "proj_runner",
        "us_runner",
        invocation_input={"runner_result": {"status": "passed", "runner_job_id": "stub_job"}},
    )

    assert outcome.failed is False
    assert outcome.run.status == "passed"
    assert outcome.run.runner_job_id == "stub_job"
    assert outcome.runner_mode == "protocol_stub"
    assert any(item.evidence_type == "report" for item in outcome.evidence)


def test_legacy_run_workspace_synchronizes_projection_and_quality_repository():
    repository = RecordingQualityLoopRepository()
    us_item = USItem(
        id="us_runner",
        title="Checkout resilience",
        owner="Quality",
        status="In progress",
        risk="medium",
        progress=50,
        next_action="Run automation",
    )
    projection_lock = RLock()
    state = SimpleNamespace(
        us_items={"proj_runner": [us_item]},
        run_details={},
        runs={"proj_runner": []},
        execution_evidence={"proj_runner": []},
    )
    adapters = SimpleNamespace(
        mutation_guard=lambda: projection_lock,
        quality_loop_repository=repository,
    )
    workspace = LegacyQualityRunWorkspace(state, adapters)
    run = RunDetail(
        id="run_runner",
        status="passed",
        channel="web_runner",
        title="Checkout validation",
        summary="Passed.",
        started_at="2026-07-30T00:00:00Z",
        failure_summary="",
        healing_status="not_required",
    )
    evidence = ExecutionEvidence(
        id="ev_runner",
        project_id="proj_runner",
        run_id=run.id,
        us_id=us_item.id,
        evidence_type="report",
        storage_ref="s3://nasus-artifacts/evidence/report.json",
        content_hash="sha256:runner",
        producer="web_runner",
        captured_at="2026-07-30T00:00:01Z",
    )

    assert workspace.us_title("proj_runner", us_item.id) == us_item.title
    workspace.save_run_detail("proj_runner", run)
    workspace.replace_run_evidence("proj_runner", run.id, [evidence])

    assert repository.runs[0].id == run.id
    assert repository.evidence[0].id == evidence.id
    assert state.run_details[run.id].id == run.id
    assert state.runs["proj_runner"][0].id == run.id
    assert state.execution_evidence["proj_runner"][0].id == evidence.id
    assert state.run_details[run.id] is not run
    assert state.execution_evidence["proj_runner"][0] is not evidence


def test_http_runner_maps_authenticated_runner_response(monkeypatch):
    screenshot = base64.b64encode(b"png-bytes").decode("ascii")
    captured = {}

    class StubResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "runner_job_id": "job_http",
                "status": "passed",
                "summary": "Browser steps passed.",
                "failure_summary": "",
                "started_at": "2026-07-29T00:00:00Z",
                "completed_at": "2026-07-29T00:00:01Z",
                "timeline": ["Step 1 passed"],
                "artifacts": [
                    {
                        "artifact_type": "screenshot",
                        "name": "final.png",
                        "media_type": "image/png",
                        "content_base64": screenshot,
                    }
                ],
            }

    def fake_post(url, *, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return StubResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    runner = HttpAutomationRunner(
        "http://runner.internal:8090",
        "runner-service-token",
        request_timeout_seconds=12,
    )
    with actor_scope(
        UserProfile(
            id="user_runner",
            name="Runner User",
            email="runner@example.com",
            role="qa_lead",
        ),
        request_id="request:runner-adapter",
    ):
        result = runner.execute(
            AutomationRunnerCommand(
                job_id="job_http",
                project_id="proj_runner",
                us_id="us_runner",
                base_url="https://app.example.com",
                steps=({"action": "goto", "path": "/"},),
                timeout_ms=10_000,
            )
        )

    assert result.status == "passed"
    assert result.runner_mode == "http_playwright"
    assert result.artifacts[0].content_base64 == screenshot
    assert captured["url"] == "http://runner.internal:8090/v1/jobs"
    assert captured["headers"]["Authorization"] == "Bearer runner-service-token"
    assert captured["headers"]["X-Request-ID"] == "request:runner-adapter"
    assert captured["json"]["steps"] == [{"action": "goto", "path": "/"}]
