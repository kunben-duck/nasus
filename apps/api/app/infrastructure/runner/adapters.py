from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from typing import Any

import httpx

from ...application.platform.actor_context import current_actor
from ...application.quality_loop.runner_port import (
    AutomationRunnerCommand,
    AutomationRunnerPort,
    AutomationRunnerResult,
    RunnerArtifact,
)
from ...domain.quality_loop.runner_observations import verify_runner_observations
from ...domain.quality_loop.http_runner_observations import verify_http_runner_observations
from .http_observation_artifacts import verify_http_response_artifacts
from .request_wire import runner_request_body


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(job_id: str, reason: str) -> str:
    return f"sha256:{hashlib.sha256(f'{job_id}:{reason}'.encode()).hexdigest()}"


class FailClosedAutomationRunner:
    """Returns an explicit failed execution when no trusted runner is configured."""

    def execute(self, command: AutomationRunnerCommand) -> AutomationRunnerResult:
        now = _now_iso()
        return AutomationRunnerResult(
            runner_job_id=command.job_id,
            status="error",
            summary="Automation was not executed because no trusted runner is configured.",
            failure_summary=(
                "Configure NASUS_RUNNER_MODE=http, NASUS_RUNNER_ENDPOINT, and "
                "NASUS_RUNNER_SERVICE_TOKEN before producing execution evidence."
            ),
            started_at=now,
            completed_at=now,
            timeline=("Runner configuration validation failed before execution.",),
            failure_fingerprint=_fingerprint(command.job_id, "runner_not_configured"),
            runner_mode="unavailable",
        )


class HttpAutomationRunner:
    """Calls the isolated browser/HTTP runner over its authenticated internal API."""

    def __init__(
        self,
        endpoint: str,
        service_token: str,
        *,
        request_timeout_seconds: float = 130.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.service_token = service_token
        self.request_timeout_seconds = request_timeout_seconds

    def execute(self, command: AutomationRunnerCommand) -> AutomationRunnerResult:
        try:
            actor = current_actor()
            request_id = actor.request_id if actor is not None else None
            headers = {
                "Authorization": f"Bearer {self.service_token}",
                "Content-Type": "application/json",
            }
            if request_id:
                headers["X-Request-ID"] = request_id
            body = runner_request_body(command)
            request_hash = "sha256:" + hashlib.sha256(body).hexdigest()
            response = httpx.post(
                f"{self.endpoint}/v1/jobs",
                headers=headers,
                content=body,
                timeout=self.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("runner response is not a JSON object")
            return self._result_from_payload(command, payload, request_hash=request_hash)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            now = _now_iso()
            reason = "Runner transport or execution receipt validation failed."
            return AutomationRunnerResult(
                runner_job_id=command.job_id,
                status="error",
                summary="The isolated automation runner could not complete the job.",
                failure_summary=reason,
                started_at=now,
                completed_at=now,
                timeline=("Runner request failed closed.",),
                failure_fingerprint=_fingerprint(command.job_id, reason),
                runner_mode="http_native" if command.kind == "http" else "http_playwright",
            )

    @staticmethod
    def _result_from_payload(
        command: AutomationRunnerCommand,
        payload: dict[str, Any],
        *, request_hash: str,
    ) -> AutomationRunnerResult:
        status = payload.get("status")
        if payload.get("runner_job_id") != command.job_id:
            raise ValueError("runner response job mismatch")
        scope = dict(job_id=command.job_id, project_id=command.project_id, us_id=command.us_id,
            request_hash=request_hash, status=status)
        if command.kind == "http":
            if getattr(command, "fixture_input", None) is not None:
                from .http_fixture_input_verifier import verify_http_fixture_input
                verify_http_fixture_input(command)
            receipt = verify_http_runner_observations(payload.get("execution_receipt"), steps=command.steps,
                protocol=command.http_protocol, fixture_input=getattr(command, "fixture_input", None), base_url=command.base_url,
                metadata=command.metadata, **scope)
            verify_http_response_artifacts(receipt, payload.get("artifacts"), command.steps)
        else:
            receipt = verify_runner_observations(payload.get("execution_receipt"),
                step_actions=tuple(step.get("action") for step in command.steps), **scope)
        artifacts = tuple(
            RunnerArtifact(
                artifact_type=str(item.get("artifact_type") or "report"),
                name=str(item.get("name") or "runner-artifact"),
                media_type=str(item.get("media_type") or "application/octet-stream"),
                content_base64=str(item.get("content_base64") or ""),
            )
            for item in payload.get("artifacts", [])
            if isinstance(item, dict) and (item.get("content_base64") or command.kind == "http" and item.get("content_base64") == "")
        )
        now = _now_iso()
        failure_summary = str(payload.get("failure_summary") or "")
        return AutomationRunnerResult(
            runner_job_id=str(payload.get("runner_job_id") or command.job_id),
            status=status,  # type: ignore[arg-type]
            summary=str(payload.get("summary") or f"Runner completed with status {status}."),
            failure_summary=failure_summary,
            started_at=str(payload.get("started_at") or now),
            completed_at=str(payload.get("completed_at") or now),
            timeline=tuple(str(item) for item in payload.get("timeline", []) if str(item)),
            artifacts=artifacts,
            failure_fingerprint=(
                str(payload.get("failure_fingerprint"))
                if payload.get("failure_fingerprint")
                else _fingerprint(command.job_id, failure_summary or status)
            ),
            runner_mode="http_native" if command.kind == "http" else "http_playwright",
            execution_receipt=receipt,
        )


class ProtocolStubAutomationRunner:
    """Test-only adapter for protocol and domain-state tests."""

    def __init__(self, result_payload: dict[str, Any] | None = None) -> None:
        self.result_payload = result_payload or {}

    def execute(self, command: AutomationRunnerCommand) -> AutomationRunnerResult:
        payload = self.result_payload
        raw_status = str(payload.get("status") or "passed").lower()
        status = "failed" if raw_status in {"failed", "failure", "error", "timed_out"} else "passed"
        now = _now_iso()
        failure_summary = str(
            payload.get("failure_summary")
            or ("Protocol stub was instructed to return a failed execution." if status == "failed" else "")
        )
        return AutomationRunnerResult(
            runner_job_id=str(payload.get("runner_job_id") or f"stub_{command.job_id}"),
            status=status,
            summary=str(
                payload.get("summary")
                or (
                    "Protocol stub returned a failed execution."
                    if status == "failed"
                    else "Protocol stub validated the runner result envelope."
                )
            ),
            failure_summary=failure_summary,
            started_at=str(payload.get("started_at") or now),
            completed_at=str(payload.get("completed_at") or now),
            timeline=tuple(str(item) for item in payload.get("timeline", []) if str(item)),
            failure_fingerprint=(
                str(payload.get("failure_fingerprint"))
                if payload.get("failure_fingerprint")
                else (_fingerprint(command.job_id, failure_summary) if status == "failed" else None)
            ),
            runner_mode="protocol_stub",
        )


def build_automation_runner_from_env(
    *,
    test_result_payload: dict[str, Any] | None = None,
) -> AutomationRunnerPort:
    mode = os.getenv("NASUS_RUNNER_MODE", "unavailable").strip().lower()
    if mode == "http":
        endpoint = os.getenv("NASUS_RUNNER_ENDPOINT", "").strip()
        service_token = os.getenv("NASUS_RUNNER_SERVICE_TOKEN", "").strip()
        if endpoint and service_token:
            timeout = max(1.0, float(os.getenv("NASUS_RUNNER_REQUEST_TIMEOUT_SECONDS", "130")))
            return HttpAutomationRunner(endpoint, service_token, request_timeout_seconds=timeout)
        return FailClosedAutomationRunner()
    if mode == "protocol_stub":
        return ProtocolStubAutomationRunner(test_result_payload)
    return FailClosedAutomationRunner()


__all__ = [
    "FailClosedAutomationRunner",
    "HttpAutomationRunner",
    "ProtocolStubAutomationRunner",
    "build_automation_runner_from_env",
]
