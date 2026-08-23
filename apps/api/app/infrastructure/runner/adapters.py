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
    """Calls the isolated Playwright runner over its authenticated internal API."""

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
            response = httpx.post(
                f"{self.endpoint}/v1/jobs",
                headers=headers,
                json={
                    "job_id": command.job_id,
                    "project_id": command.project_id,
                    "us_id": command.us_id,
                    "base_url": command.base_url,
                    "steps": list(command.steps),
                    "timeout_ms": command.timeout_ms,
                    "metadata": command.metadata,
                },
                timeout=self.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("runner response is not a JSON object")
            return self._result_from_payload(command, payload)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            now = _now_iso()
            reason = f"{type(exc).__name__}: {exc}"
            return AutomationRunnerResult(
                runner_job_id=command.job_id,
                status="error",
                summary="The isolated automation runner could not complete the job.",
                failure_summary=reason,
                started_at=now,
                completed_at=now,
                timeline=("Runner request failed closed.",),
                failure_fingerprint=_fingerprint(command.job_id, reason),
                runner_mode="http_playwright",
            )

    @staticmethod
    def _result_from_payload(
        command: AutomationRunnerCommand,
        payload: dict[str, Any],
    ) -> AutomationRunnerResult:
        raw_status = str(payload.get("status") or "error").lower()
        status = raw_status if raw_status in {"passed", "failed", "error", "timed_out"} else "error"
        artifacts = tuple(
            RunnerArtifact(
                artifact_type=str(item.get("artifact_type") or "report"),
                name=str(item.get("name") or "runner-artifact"),
                media_type=str(item.get("media_type") or "application/octet-stream"),
                content_base64=str(item.get("content_base64") or ""),
            )
            for item in payload.get("artifacts", [])
            if isinstance(item, dict) and item.get("content_base64")
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
            runner_mode="http_playwright",
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
