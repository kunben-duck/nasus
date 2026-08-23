from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from ...application.quality_loop.runner_port import (
    AutomationExecutionOutcome,
    AutomationRunnerCommand,
    AutomationRunnerPort,
    AutomationRunnerResult,
    EvidenceObjectStoragePort,
    QualityRunWorkspacePort,
    RunnerArtifact,
)
from ...application.quality_loop.quality_models import ExecutionEvidence, RunDetail
from ...application.system_image.system_image_models import TaskContext
from .adapters import build_automation_runner_from_env


SUPPORTED_EVIDENCE_TYPES = {
    "script",
    "trace",
    "log",
    "screenshot",
    "video",
    "report",
    "failure_artifact",
}
SAFE_ARTIFACT_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class RunTaskContextProvider(Protocol):
    def current_task_context(self, project_id: str, us_id: str | None = None) -> TaskContext | None:
        ...


RunExecutionOutcome = AutomationExecutionOutcome


class RunOrchestrator:
    """Execute automation through a trusted runner and persist canonical evidence."""

    def __init__(
        self,
        workspace: QualityRunWorkspacePort,
        task_context_provider: RunTaskContextProvider,
        evidence_storage: EvidenceObjectStoragePort,
        *,
        runner: AutomationRunnerPort | None = None,
    ) -> None:
        self.workspace = workspace
        self.task_context_provider = task_context_provider
        self.evidence_storage = evidence_storage
        self.runner = runner

    def execute_automation(
        self,
        project_id: str,
        us_id: str,
        *,
        invocation_input: dict[str, Any],
    ) -> RunExecutionOutcome:
        command = self._runner_command(project_id, us_id, invocation_input)
        runner = self.runner or build_automation_runner_from_env(
            test_result_payload=self._protocol_stub_result(invocation_input)
        )
        runner_result = runner.execute(command)
        run = self._build_run(project_id, us_id, runner_result, command)
        evidence = self._upsert_execution_evidence(
            project_id,
            us_id,
            run,
            runner_result=runner_result,
        )
        run.evidence = [item.storage_ref for item in evidence]
        self._persist_run_detail(project_id, run)
        return RunExecutionOutcome(
            run=run,
            evidence=evidence,
            runner_mode=runner_result.runner_mode,
        )

    def materialize_evidence(
        self,
        project_id: str,
        us_id: str,
        run: RunDetail,
    ) -> list[ExecutionEvidence]:
        return self._upsert_execution_evidence(project_id, us_id, run)

    @staticmethod
    def _protocol_stub_result(invocation_input: dict[str, Any]) -> dict[str, Any] | None:
        if os.getenv("NASUS_RUNNER_MODE", "unavailable").strip().lower() != "protocol_stub":
            return None
        result = invocation_input.get("runner_result")
        return result if isinstance(result, dict) else None

    def _runner_command(
        self,
        project_id: str,
        us_id: str,
        invocation_input: dict[str, Any],
    ) -> AutomationRunnerCommand:
        runner_request = invocation_input.get("runner_request")
        request = runner_request if isinstance(runner_request, dict) else {}
        raw_steps = request.get("steps")
        if not isinstance(raw_steps, list):
            raw_steps = invocation_input.get("steps")
        steps = tuple(dict(item) for item in raw_steps if isinstance(item, dict)) if isinstance(raw_steps, list) else ()
        raw_timeout = request.get("timeout_ms", invocation_input.get("timeout_ms", 60_000))
        try:
            timeout_ms = int(raw_timeout)
        except (TypeError, ValueError):
            timeout_ms = 60_000
        timeout_ms = min(max(timeout_ms, 1_000), 120_000)
        metadata = {
            "environment_id": request.get("environment_id") or invocation_input.get("environment_id"),
            "browser": request.get("browser") or "chromium",
            "automation_asset_ref": request.get("automation_asset_ref") or "automation_asset:current",
            "automation_script_id": request.get("automation_script_id"),
            "retry_of_run_id": request.get("retry_of_run_id"),
            "attempt": request.get("attempt") or 1,
            "task_context_id": self._task_context_id(project_id, us_id),
        }
        return AutomationRunnerCommand(
            job_id=f"runner_job_{uuid4().hex}",
            project_id=project_id,
            us_id=us_id,
            base_url=str(request.get("base_url") or invocation_input.get("base_url") or "").strip(),
            steps=steps,
            timeout_ms=timeout_ms,
            metadata={key: value for key, value in metadata.items() if value is not None},
        )

    def _build_run(
        self,
        project_id: str,
        us_id: str,
        runner_result: AutomationRunnerResult,
        command: AutomationRunnerCommand,
    ) -> RunDetail:
        us_title = self.workspace.us_title(project_id, us_id) or us_id
        run_id = f"run_{uuid4().hex}"
        status = "passed" if runner_result.status == "passed" else "failed"
        task_context_id = self._task_context_id(project_id, us_id) or ""
        failure_summary = runner_result.failure_summary
        if status == "failed" and not failure_summary:
            failure_summary = f"Runner completed with non-passing status {runner_result.status}."
        retry_of_run_id = command.metadata.get("retry_of_run_id")
        try:
            attempt = max(int(command.metadata.get("attempt") or 1), 1)
        except (TypeError, ValueError):
            attempt = 1
        return RunDetail(
            id=run_id,
            status=status,
            channel="web_runner",
            title=(
                f"{us_title} automation validation"
                if attempt == 1
                else f"{us_title} automation validation (attempt {attempt})"
            ),
            summary=runner_result.summary,
            started_at=runner_result.started_at or self._now(),
            task_context_id=task_context_id or None,
            runner_job_id=runner_result.runner_job_id,
            timeline=list(runner_result.timeline) or self._default_timeline(status),
            evidence=[],
            failure_summary=failure_summary,
            healing_status="not_started" if status == "failed" else "not_required",
            healing_depth=0,
            last_failure_fingerprint=runner_result.failure_fingerprint,
            us_id=us_id,
            target_base_url=command.base_url or None,
            automation_asset_ref=str(command.metadata.get("automation_asset_ref") or "") or None,
            automation_script_id=str(command.metadata.get("automation_script_id") or "") or None,
            execution_plan=[dict(step) for step in command.steps],
            execution_timeout_ms=command.timeout_ms,
            retry_of_run_id=str(retry_of_run_id) if retry_of_run_id else None,
            attempt=attempt,
        )

    def _task_context_id(self, project_id: str, us_id: str) -> str | None:
        context = self.task_context_provider.current_task_context(project_id, us_id)
        return context.id if context is not None else None

    def _persist_run_detail(self, project_id: str, run: RunDetail) -> None:
        self.workspace.save_run_detail(project_id, run)

    def _upsert_execution_evidence(
        self,
        project_id: str,
        us_id: str,
        run: RunDetail,
        *,
        runner_result: AutomationRunnerResult | None = None,
    ) -> list[ExecutionEvidence]:
        captured_at = self._now()
        evidence: list[ExecutionEvidence] = []
        artifacts = list(runner_result.artifacts) if runner_result is not None else []
        artifacts.append(self._result_report_artifact(run, runner_result))
        if run.status == "failed" and not any(item.artifact_type == "failure_artifact" for item in artifacts):
            artifacts.append(self._failure_artifact(run))

        max_artifact_bytes = max(1, int(os.getenv("NASUS_RUNNER_MAX_ARTIFACT_BYTES", str(25 * 1024 * 1024))))
        for index, artifact in enumerate(artifacts):
            evidence_type = artifact.artifact_type if artifact.artifact_type in SUPPORTED_EVIDENCE_TYPES else "report"
            body = self._decode_artifact(artifact, max_artifact_bytes=max_artifact_bytes)
            artifact_hash = hashlib.sha256(body).hexdigest()
            safe_name = SAFE_ARTIFACT_NAME.sub("-", artifact.name).strip(".-") or f"artifact-{index}"
            object_result = self.evidence_storage.put_bytes(
                f"evidence/{project_id}/{run.id}/{evidence_type}/{artifact_hash[:16]}-{safe_name}",
                body,
                content_type=artifact.media_type or "application/octet-stream",
            )
            evidence.append(
                ExecutionEvidence(
                    id=f"ev_{hashlib.sha256(f'{run.id}:{index}:{artifact_hash}'.encode()).hexdigest()[:16]}",
                    project_id=project_id,
                    run_id=run.id,
                    us_id=us_id,
                    case_ref="case_set:current",
                    evidence_type=evidence_type,  # type: ignore[arg-type]
                    storage_ref=object_result.storage_ref,
                    content_hash=object_result.content_hash,
                    producer="web_runner",
                    captured_at=captured_at,
                )
            )
        self.workspace.replace_run_evidence(
            project_id,
            run.id,
            evidence,
        )
        return evidence

    @staticmethod
    def _default_timeline(status: str) -> list[str]:
        if status == "failed":
            return [
                "Generated browser automation from approved cases.",
                "The isolated runner returned a non-passing result.",
                "Captured available runner artifacts for failure analysis.",
            ]
        return [
            "Generated browser automation from approved cases.",
            "The isolated runner completed browser validation.",
            "Captured runner artifacts for review.",
        ]

    @staticmethod
    def _decode_artifact(artifact: RunnerArtifact, *, max_artifact_bytes: int) -> bytes:
        try:
            body = base64.b64decode(artifact.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RuntimeError(f"Runner returned invalid base64 artifact {artifact.name!r}") from exc
        if len(body) > max_artifact_bytes:
            raise RuntimeError(
                f"Runner artifact {artifact.name!r} exceeds the {max_artifact_bytes} byte limit"
            )
        return body

    @staticmethod
    def _result_report_artifact(
        run: RunDetail,
        runner_result: AutomationRunnerResult | None,
    ) -> RunnerArtifact:
        payload = {
            "run_id": run.id,
            "runner_job_id": run.runner_job_id,
            "task_context_id": run.task_context_id,
            "status": run.status,
            "summary": run.summary,
            "failure_summary": run.failure_summary,
            "timeline": run.timeline,
            "runner_mode": runner_result.runner_mode if runner_result else "materialized",
            "runner_status": runner_result.status if runner_result else run.status,
            "started_at": runner_result.started_at if runner_result else run.started_at,
            "completed_at": runner_result.completed_at if runner_result else None,
        }
        return RunnerArtifact(
            artifact_type="report",
            name="runner-result.json",
            media_type="application/json",
            content_base64=base64.b64encode(
                json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).decode("ascii"),
        )

    @staticmethod
    def _failure_artifact(run: RunDetail) -> RunnerArtifact:
        payload = {
            "run_id": run.id,
            "runner_job_id": run.runner_job_id,
            "failure_summary": run.failure_summary,
            "failure_fingerprint": run.last_failure_fingerprint,
        }
        return RunnerArtifact(
            artifact_type="failure_artifact",
            name="failure.json",
            media_type="application/json",
            content_base64=base64.b64encode(
                json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).decode("ascii"),
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
