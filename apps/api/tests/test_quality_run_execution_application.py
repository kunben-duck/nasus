from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from apps.api.app.application.quality_loop.ports import (
    QualityAssetPackReadPort,
)
from apps.api.app.application.quality_loop.quality_models import (
    ExecutionEvidence,
    QualityAssetPack,
    QualityAssetPart,
    RunDetail,
)
from apps.api.app.application.quality_loop.results import (
    QualityLoopApplicationError,
)
from apps.api.app.application.quality_loop.run_execution import (
    QualityRunExecutionApplicationService,
)
from apps.api.app.application.quality_loop.runner_port import (
    AutomationExecutionOutcome,
)


@dataclass
class InMemoryAssetPackReader(QualityAssetPackReadPort):
    packs: dict[tuple[str, str], QualityAssetPack] = field(
        default_factory=dict
    )

    def get_quality_asset_pack(
        self,
        project_id: str,
        us_id: str,
    ) -> QualityAssetPack | None:
        return self.packs.get((project_id, us_id))


@dataclass
class InMemoryEvidenceReader:
    evidence: dict[str, list[ExecutionEvidence]] = field(
        default_factory=dict
    )

    def list_execution_evidence(
        self,
        project_id: str,
    ) -> list[ExecutionEvidence]:
        return list(self.evidence.get(project_id, []))


@dataclass
class RecordingAutomationExecutor:
    outcome: AutomationExecutionOutcome
    calls: list[tuple[str, str, dict[str, Any]]] = field(
        default_factory=list
    )

    def execute_automation(
        self,
        project_id: str,
        us_id: str,
        *,
        invocation_input: dict[str, Any],
    ) -> AutomationExecutionOutcome:
        self.calls.append((project_id, us_id, invocation_input))
        return self.outcome

    def materialize_evidence(
        self,
        project_id: str,
        us_id: str,
        run: RunDetail,
    ) -> list[ExecutionEvidence]:
        del project_id, us_id, run
        return list(self.outcome.evidence)


def evidence(
    evidence_id: str,
    *,
    project_id: str = "proj_a",
    us_id: str = "US-A1",
) -> ExecutionEvidence:
    return ExecutionEvidence(
        id=evidence_id,
        project_id=project_id,
        run_id="run_a",
        us_id=us_id,
        evidence_type="report",
        storage_ref=f"s3://nasus-artifacts/{evidence_id}",
        content_hash=f"sha256:{evidence_id}",
        producer="web_runner",
        captured_at="2026-07-30T00:00:00+00:00",
    )


def run() -> RunDetail:
    return RunDetail(
        id="run_a",
        status="passed",
        channel="web_runner",
        title="Checkout automation validation",
        summary="Browser validation passed.",
        started_at="2026-07-30T00:00:00+00:00",
        failure_summary="",
        healing_status="not_required",
    )


def automation_pack() -> QualityAssetPack:
    part = QualityAssetPart(
        id="qap_proj_a_US-A1_automation_blueprint",
        part_type="automation_blueprint",
        status="approved",
        title="Checkout automation",
        summary="Approved Playwright blueprint.",
        revision=3,
        structured_content={
            "default_base_url": "https://app.example.com",
            "scripts": [
                {
                    "script_id": "script_checkout",
                    "title": "Validate checkout",
                    "linked_case_ids": ["case_checkout"],
                    "timeout_ms": 20_000,
                    "steps": [
                        {"action": "goto", "path": "/checkout"},
                        {
                            "action": "assert_visible",
                            "selector": "[data-testid=checkout]",
                        },
                    ],
                }
            ],
        },
        updated_at="2026-07-30T00:00:00+00:00",
    )
    return QualityAssetPack(
        id="qap_proj_a_US-A1",
        project_id="proj_a",
        version_id="ver_a",
        us_id="US-A1",
        status="approved",
        current_revision=3,
        parts=[part],
        updated_at="2026-07-30T00:00:00+00:00",
    )


def service_with_pack() -> tuple[
    QualityRunExecutionApplicationService,
    RecordingAutomationExecutor,
    InMemoryEvidenceReader,
]:
    execution_evidence = evidence("ev_run_a")
    executor = RecordingAutomationExecutor(
        AutomationExecutionOutcome(
            run=run(),
            evidence=[execution_evidence],
            runner_mode="http_playwright",
        )
    )
    packs = InMemoryAssetPackReader(
        packs={
            ("proj_a", "US-A1"): automation_pack(),
        }
    )
    evidence_reader = InMemoryEvidenceReader(
        evidence={"proj_a": [execution_evidence]}
    )
    return (
        QualityRunExecutionApplicationService(
            executor,
            packs,
            evidence_reader,
        ),
        executor,
        evidence_reader,
    )


def test_run_execution_uses_durable_pack_and_trusted_executor_ports() -> None:
    service, executor, _ = service_with_pack()

    result = service.execute_automation(
        "proj_a",
        "US-A1",
        invocation_input={"automation_script_id": "script_checkout"},
    )

    assert result.run.id == "run_a"
    assert result.failed is False
    assert result.runner_mode == "http_playwright"
    assert result.automation_asset_ref.endswith(
        "qap_proj_a_US-A1_automation_blueprint:revision:3"
    )
    assert result.evidence_refs == ["execution_evidence:ev_run_a"]
    assert result.script_id == "script_checkout"
    _, _, invocation_input = executor.calls[0]
    request = invocation_input["runner_request"]
    assert request["base_url"] == "https://app.example.com"
    assert request["timeout_ms"] == 20_000
    assert request["automation_script_id"] == "script_checkout"
    assert request["attempt"] == 1
    assert request["steps"] == [
        {"action": "goto", "path": "/checkout"},
        {
            "action": "assert_visible",
            "selector": "[data-testid=checkout]",
        },
    ]


def test_run_execution_rejects_missing_or_unknown_automation_script() -> None:
    service, _, _ = service_with_pack()

    with pytest.raises(
        QualityLoopApplicationError,
        match="does not exist",
    ):
        service.execute_automation(
            "proj_a",
            "US-A1",
            invocation_input={"automation_script_id": "script_missing"},
        )

    empty_service = QualityRunExecutionApplicationService(
        RecordingAutomationExecutor(
            AutomationExecutionOutcome(
                run=run(),
                evidence=[],
                runner_mode="http_playwright",
            )
        ),
        InMemoryAssetPackReader(),
        InMemoryEvidenceReader(),
    )
    with pytest.raises(
        QualityLoopApplicationError,
        match="requires a generated automation blueprint",
    ):
        empty_service.execute_automation(
            "proj_a",
            "US-A1",
            invocation_input={},
        )


def test_run_execution_reads_evidence_refs_from_durable_port() -> None:
    service, _, evidence_reader = service_with_pack()
    evidence_reader.evidence["proj_a"].append(
        evidence("ev_other_us", us_id="US-A2")
    )

    assert service.evidence_refs_for_us("proj_a", "US-A1") == [
        "execution_evidence:ev_run_a"
    ]
    assert service.evidence_refs_for_us(
        "proj_missing",
        "US-X",
        fallback_refs=["evidence:fallback"],
    ) == ["evidence:fallback"]


def test_run_retry_replays_only_persisted_execution_context() -> None:
    service, executor, _ = service_with_pack()
    source_run = run().model_copy(
        update={
            "id": "run_source",
            "status": "failed",
            "us_id": "US-A1",
            "target_base_url": "https://original.example.com",
            "automation_asset_ref": (
                "quality_asset_part:qap_proj_a_US-A1_automation_blueprint:revision:3"
            ),
            "automation_script_id": "script_checkout",
            "execution_plan": [
                {"action": "goto", "path": "/checkout"},
                {
                    "action": "assert_visible",
                    "selector": "[data-testid=checkout]",
                },
            ],
            "execution_timeout_ms": 20_000,
            "attempt": 2,
        }
    )

    result = service.retry_automation(
        "proj_a",
        "US-A1",
        source_run=source_run,
    )

    assert result.automation_asset_ref.endswith("revision:3")
    _, _, invocation_input = executor.calls[0]
    request = invocation_input["runner_request"]
    assert request == {
        "base_url": "https://original.example.com",
        "steps": source_run.execution_plan,
        "timeout_ms": 20_000,
        "automation_asset_ref": source_run.automation_asset_ref,
        "automation_script_id": "script_checkout",
        "retry_of_run_id": "run_source",
        "attempt": 3,
    }


def test_run_retry_fails_closed_without_persisted_execution_context() -> None:
    service, _, _ = service_with_pack()

    with pytest.raises(
        QualityLoopApplicationError,
        match="predates persisted execution targets",
    ):
        service.retry_automation(
            "proj_a",
            "US-A1",
            source_run=run(),
        )
