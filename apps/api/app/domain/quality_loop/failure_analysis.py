from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol


class FailedRunLike(Protocol):
    id: str
    summary: str
    failure_summary: str | None
    evidence: list[str]


@dataclass(frozen=True)
class FailureIdentity:
    fingerprint: str
    report_id: str


@dataclass(frozen=True)
class FailureReportDecision:
    identity: FailureIdentity
    failure_kind: str
    summary: str
    root_cause: str
    status: str
    healing_attempt_count: int
    fallback_to_human: bool
    run_healing_status: str


def identify_failure(project_id: str, us_id: str, run: FailedRunLike) -> FailureIdentity:
    fingerprint = hashlib.sha256(
        (
            f"{project_id}:{us_id}:{run.id}:"
            f"{run.failure_summary or run.summary}:{'|'.join(sorted(run.evidence))}"
        ).encode("utf-8")
    ).hexdigest()[:16]
    return FailureIdentity(
        fingerprint=fingerprint,
        report_id=f"failure_{run.id}_{fingerprint}",
    )


def classify_failure_kind(run: FailedRunLike) -> str:
    text = f"{run.failure_summary} {run.summary}".lower()
    if "selector" in text or "dom" in text:
        return "selector"
    if "timeout" in text:
        return "timeout"
    if "network" in text or "redirect" in text:
        return "network"
    if "data" in text:
        return "data"
    if "assert" in text or "assertion" in text:
        return "assertion"
    return "unknown"


def decide_failure_report(
    project_id: str,
    us_id: str,
    run: FailedRunLike,
    *,
    existing_healing_attempt_count: int = 0,
    increment_healing_attempt: bool,
    max_healing_depth: int,
) -> FailureReportDecision:
    identity = identify_failure(project_id, us_id, run)
    attempt_count = existing_healing_attempt_count + (1 if increment_healing_attempt else 0)
    fallback_to_human = attempt_count >= max_healing_depth
    status = (
        "fallback_to_human"
        if fallback_to_human
        else ("healing_proposed" if increment_healing_attempt else "under_review")
    )
    return FailureReportDecision(
        identity=identity,
        failure_kind=classify_failure_kind(run),
        summary=run.failure_summary or run.summary or "Run failed and requires structured analysis.",
        root_cause=(
            "Repeated failure fingerprint reached the automatic healing limit; human review is required."
            if fallback_to_human
            else "Failure appears tied to selector/assertion drift in the generated automation path."
        ),
        status=status,
        healing_attempt_count=attempt_count,
        fallback_to_human=fallback_to_human,
        run_healing_status=status,
    )
