from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ReleaseReadinessLike(Protocol):
    version_id: str
    score: int
    blockers: int
    approvals_open: int
    pending_merge: int


@dataclass(frozen=True)
class ReleaseDecisionDraft:
    id: str
    project_id: str
    version_id: str
    us_id: str | None
    status: str
    score: int
    rationale: str
    evidence_refs: list[str]


def decide_release_decision(
    *,
    project_id: str,
    us_id: str | None,
    readiness: ReleaseReadinessLike,
    execution_evidence_refs: list[str],
) -> ReleaseDecisionDraft:
    status = release_decision_status(readiness, execution_evidence_refs)
    return ReleaseDecisionDraft(
        id=release_decision_id(project_id, readiness.version_id, us_id),
        project_id=project_id,
        version_id=readiness.version_id,
        us_id=us_id,
        status=status,
        score=readiness.score,
        rationale=release_decision_rationale(status, readiness, execution_evidence_refs),
        evidence_refs=[f"release_readiness:{readiness.version_id}", *execution_evidence_refs],
    )


def release_decision_id(project_id: str, version_id: str, us_id: str | None) -> str:
    return f"release_decision_{project_id}_{version_id}_{us_id or 'all'}"


def release_decision_status(readiness: ReleaseReadinessLike, execution_evidence_refs: list[str]) -> str:
    if readiness.score < 60 or readiness.blockers:
        return "blocked"
    if readiness.score < 80 or readiness.approvals_open or readiness.pending_merge:
        return "conditional"
    if not execution_evidence_refs:
        return "needs_evidence"
    return "ready"


def release_decision_rationale(
    status: str,
    readiness: ReleaseReadinessLike,
    execution_evidence_refs: list[str],
) -> str:
    return (
        f"Release decision is {status}: score={readiness.score}, blockers={readiness.blockers}, "
        f"approvals_open={readiness.approvals_open}, pending_merge={readiness.pending_merge}, "
        f"evidence_count={len(execution_evidence_refs)}."
    )
