from __future__ import annotations

import os

import httpx

from ..config.runtime_config import current_runtime_profile


class AutomationRunnerReadinessProbe:
    """Checks the isolated execution service without submitting a job."""

    name = "automation_runner"

    def __init__(
        self,
        *,
        mode: str | None = None,
        endpoint: str | None = None,
        timeout_seconds: float = 2.0,
    ) -> None:
        self._mode = (mode or os.getenv("NASUS_RUNNER_MODE", "unavailable")).strip().lower()
        self._endpoint = (endpoint or os.getenv("NASUS_RUNNER_ENDPOINT", "")).strip().rstrip("/")
        self._timeout_seconds = max(0.1, timeout_seconds)

    def check(self) -> dict[str, str]:
        if self._mode == "http":
            if not self._endpoint:
                raise RuntimeError("NASUS_RUNNER_ENDPOINT is required for the HTTP runner")
            response = httpx.get(
                f"{self._endpoint}/readyz",
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("status") != "ready":
                raise RuntimeError("automation runner did not report ready")
            return {
                "backend": "http_playwright",
                "endpoint": self._endpoint,
                "browser": str(payload.get("browser") or "unknown"),
            }

        if current_runtime_profile().production_like:
            raise RuntimeError("production requires NASUS_RUNNER_MODE=http")
        if self._mode == "protocol_stub":
            return {
                "backend": "protocol_stub",
                "policy": "test-only",
            }
        return {
            "backend": "disabled",
            "policy": "fail-closed",
        }


__all__ = ["AutomationRunnerReadinessProbe"]
