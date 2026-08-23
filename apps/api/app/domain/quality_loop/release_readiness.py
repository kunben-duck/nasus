from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class FailureReportLike(Protocol):
    failure_kind: str
    summary: str
    fallback_to_human: bool


@dataclass(frozen=True)
class ReleaseReadinessEvidence:
    """Normalized facts used by the release-readiness policy.

    Infrastructure and application services own fact collection. Keeping this
    snapshot primitive makes the scoring policy deterministic, replayable, and
    independent from persistence adapters, ORM models, and the LLM runtime.
    """

    run_statuses: tuple[str, ...] = ()
    evidence_types: tuple[str, ...] = ()
    asset_part_statuses: tuple[tuple[str, str], ...] = ()
    task_context_readiness: str | None = None
    task_context_confidence: float = 0
    missing_context_count: int = 0
    quality_profile_coverage: int = 0
    quality_profile_confidence: float = 0
    fallback_generated_parts: int = 0
    open_failures: tuple[FailureReportLike, ...] = ()
    approvals_open: int = 0
    pending_merge: int = 0


@dataclass(frozen=True)
class ReleaseReadinessDecision:
    status: str
    score: int
    blockers: int
    approvals_open: int
    pending_merge: int
    execution_health: str
    summary: str
    blocker_items: list[str] = field(default_factory=list)
    score_breakdown: dict[str, int] = field(default_factory=dict)
    evidence_summary: dict[str, int] = field(default_factory=dict)
    progress_floor: int = 82

    def to_api_kwargs(self, *, version_id: str) -> dict[str, object]:
        return {
            "version_id": version_id,
            "status": self.status,
            "score": self.score,
            "blockers": self.blockers,
            "approvals_open": self.approvals_open,
            "pending_merge": self.pending_merge,
            "execution_health": self.execution_health,
            "summary": self.summary,
            "blocker_items": self.blocker_items,
            "score_breakdown": self.score_breakdown,
            "evidence_summary": self.evidence_summary,
        }


REQUIRED_ASSET_PARTS = frozenset({"scenario_set", "case_set", "automation_blueprint"})
ACCEPTED_ASSET_STATUSES = frozenset({"approved", "completed"})


def decide_release_readiness(evidence: ReleaseReadinessEvidence) -> ReleaseReadinessDecision:
    run_statuses = tuple(status.strip().lower() for status in evidence.run_statuses if status)
    pass_count = sum(1 for status in run_statuses if status == "passed")
    run_count = len(run_statuses)
    evidence_type_count = len({item for item in evidence.evidence_types if item})
    latest_run_passed = bool(run_statuses) and run_statuses[0] == "passed"

    execution_score = 0
    if latest_run_passed:
        execution_score += 20
    if run_count:
        execution_score += round(10 * pass_count / run_count)
    execution_score += min(5, evidence_type_count * 2)

    part_statuses = dict(evidence.asset_part_statuses)
    accepted_parts = {
        part_type
        for part_type, status in part_statuses.items()
        if part_type in REQUIRED_ASSET_PARTS and status in ACCEPTED_ASSET_STATUSES
    }
    quality_asset_score = round(25 * len(accepted_parts) / len(REQUIRED_ASSET_PARTS))

    system_context_score = 0
    if evidence.task_context_readiness == "ready":
        system_context_score += 7
    system_context_score += round(5 * _unit_interval(evidence.task_context_confidence))
    system_context_score += round(5 * _percent(evidence.quality_profile_coverage))
    system_context_score += round(3 * _unit_interval(evidence.quality_profile_confidence))

    failure_list = list(evidence.open_failures)
    fallback_count = sum(1 for report in failure_list if report.fallback_to_human)
    approvals_open = max(max(0, evidence.approvals_open), fallback_count)
    pending_merge = max(0, evidence.pending_merge)
    governance_score = max(
        0,
        20
        - min(10, approvals_open * 5)
        - min(10, pending_merge * 10)
        - min(10, len(failure_list) * 5),
    )

    fallback_penalty = min(6, max(0, evidence.fallback_generated_parts) * 2)
    missing_context_penalty = min(9, max(0, evidence.missing_context_count) * 3)
    penalties = -(fallback_penalty + missing_context_penalty)
    score = _clamp_score(
        execution_score
        + quality_asset_score
        + system_context_score
        + governance_score
        + penalties
    )

    blocker_items: list[str] = []
    if failure_list:
        blocker_items.extend(
            f"{report.failure_kind}: {report.summary}"
            for report in failure_list
        )
    else:
        missing_parts = sorted(REQUIRED_ASSET_PARTS - accepted_parts)
        if missing_parts:
            blocker_items.append(
                "Required quality assets are not approved: " + ", ".join(missing_parts)
            )
            score = min(score, 69)
        if pass_count == 0:
            blocker_items.append("No passing automation run is available for this US.")
            score = min(score, 69)
        elif evidence_type_count == 0:
            blocker_items.append("The passing run has no persisted execution evidence.")
            score = min(score, 69)
        if evidence.task_context_readiness != "ready":
            blocker_items.append("TaskContext is missing, stale, or blocked.")
            score = min(score, 59)
        if pending_merge:
            blocker_items.append(f"{pending_merge} structured merge conflict(s) remain unresolved.")
            score = min(score, 69)

    if failure_list:
        score = min(score, 39 if fallback_count else 59)
    elif approvals_open:
        score = min(score, 79)
    if evidence.fallback_generated_parts:
        score = min(score, 84)

    execution_health = _execution_health(
        run_count=run_count,
        pass_count=pass_count,
        evidence_type_count=evidence_type_count,
        failure_count=len(failure_list),
        fallback_count=fallback_count,
    )
    score_breakdown = {
        "execution": execution_score,
        "quality_assets": quality_asset_score,
        "system_context": system_context_score,
        "governance": governance_score,
        "penalties": penalties,
        "policy_adjustment": score - (
            execution_score
            + quality_asset_score
            + system_context_score
            + governance_score
            + penalties
        ),
    }
    evidence_summary = {
        "runs": run_count,
        "passed_runs": pass_count,
        "evidence_types": evidence_type_count,
        "approved_asset_parts": len(accepted_parts),
        "required_asset_parts": len(REQUIRED_ASSET_PARTS),
        "open_failures": len(failure_list),
        "fallback_generated_parts": max(0, evidence.fallback_generated_parts),
        "missing_context_items": max(0, evidence.missing_context_count),
    }

    if failure_list:
        status = "Blocked by failure analysis"
        summary = (
            "Release readiness is blocked because failed execution evidence has unresolved FailureReports. "
            "Resolve or explicitly approve the failure disposition before baseline writeback."
        )
        progress_floor = 76
    elif blocker_items:
        status = "Needs additional release evidence"
        summary = (
            "Release readiness is not yet complete. Nasus found missing or unresolved evidence "
            "that must be addressed before formal release review."
        )
        progress_floor = 70
    elif score >= 80:
        status = "Ready for release review"
        summary = (
            "Quality assets, system context, persisted execution evidence, and governance state "
            "meet the release-review threshold. A formal ReleaseDecision still requires policy evaluation."
        )
        progress_floor = 82
    else:
        status = "Needs additional release evidence"
        summary = (
            "No hard blocker remains, but the weighted evidence score is below the release-review threshold."
        )
        progress_floor = 76

    return ReleaseReadinessDecision(
        status=status,
        score=score,
        blockers=len(blocker_items),
        approvals_open=approvals_open,
        pending_merge=pending_merge,
        execution_health=execution_health,
        summary=summary,
        blocker_items=blocker_items,
        score_breakdown=score_breakdown,
        evidence_summary=evidence_summary,
        progress_floor=progress_floor,
    )


def _execution_health(
    *,
    run_count: int,
    pass_count: int,
    evidence_type_count: int,
    failure_count: int,
    fallback_count: int,
) -> str:
    if failure_count:
        return (
            f"{failure_count} open FailureReport(s) require review; "
            f"{fallback_count} have fallen back to human handling."
        )
    if not run_count:
        return "No automation run has been recorded."
    if not pass_count:
        return f"0 of {run_count} automation run(s) passed."
    return (
        f"{pass_count} of {run_count} automation run(s) passed with "
        f"{evidence_type_count} persisted evidence type(s)."
    )


def _unit_interval(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _percent(value: int) -> float:
    return max(0.0, min(100.0, float(value))) / 100


def _clamp_score(value: int) -> int:
    return max(0, min(100, int(value)))


__all__ = [
    "FailureReportLike",
    "ReleaseReadinessDecision",
    "ReleaseReadinessEvidence",
    "decide_release_readiness",
]
