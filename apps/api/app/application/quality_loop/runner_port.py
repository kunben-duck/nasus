from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from .quality_models import ExecutionEvidence, RunDetail


RunnerStatus = Literal["passed", "failed", "error", "timed_out"]


@dataclass(frozen=True)
class AutomationRunnerCommand:
    job_id: str
    project_id: str
    us_id: str
    base_url: str
    steps: tuple[dict[str, Any], ...]
    timeout_ms: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunnerArtifact:
    artifact_type: str
    name: str
    media_type: str
    content_base64: str


@dataclass(frozen=True)
class AutomationRunnerResult:
    runner_job_id: str
    status: RunnerStatus
    summary: str
    failure_summary: str
    started_at: str
    completed_at: str
    timeline: tuple[str, ...] = ()
    artifacts: tuple[RunnerArtifact, ...] = ()
    failure_fingerprint: str | None = None
    runner_mode: str = "unavailable"


class AutomationRunnerPort(Protocol):
    def execute(self, command: AutomationRunnerCommand) -> AutomationRunnerResult:
        ...


@dataclass(frozen=True)
class AutomationExecutionOutcome:
    run: RunDetail
    evidence: list[ExecutionEvidence]
    runner_mode: str

    @property
    def failed(self) -> bool:
        return self.run.status == "failed"


class QualityAutomationExecutionPort(Protocol):
    """Trusted automation execution boundary consumed by quality use cases."""

    def execute_automation(
        self,
        project_id: str,
        us_id: str,
        *,
        invocation_input: dict[str, Any],
    ) -> AutomationExecutionOutcome:
        ...

    def materialize_evidence(
        self,
        project_id: str,
        us_id: str,
        run: RunDetail,
    ) -> list[ExecutionEvidence]:
        ...


class QualityRunWorkspacePort(Protocol):
    """Run aggregate persistence boundary used by the runner adapter."""

    def us_title(self, project_id: str, us_id: str) -> str | None:
        ...

    def save_run_detail(self, project_id: str, run: RunDetail) -> None:
        ...

    def replace_run_evidence(
        self,
        project_id: str,
        run_id: str,
        evidence: list[ExecutionEvidence],
    ) -> None:
        ...


class StoredEvidenceObject(Protocol):
    storage_ref: str
    content_hash: str


class EvidenceObjectStoragePort(Protocol):
    """Binary evidence storage boundary independent from MinIO/S3 details."""

    def put_bytes(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> StoredEvidenceObject:
        ...


__all__ = [
    "AutomationExecutionOutcome",
    "AutomationRunnerCommand",
    "AutomationRunnerPort",
    "AutomationRunnerResult",
    "EvidenceObjectStoragePort",
    "QualityAutomationExecutionPort",
    "QualityRunWorkspacePort",
    "RunnerArtifact",
    "RunnerStatus",
    "StoredEvidenceObject",
]
