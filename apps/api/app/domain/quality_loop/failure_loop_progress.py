from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


FAILURE_LOOP_PLANNER_KIND = "failure_loop_progress"
FAILURE_ANALYSIS_SUMMARY = "Analyzed failed run and created FailureReport"
FAILURE_HEALING_SUMMARY = "Prepared bounded healing proposal"
FAILURE_FALLBACK_SUMMARY = "Healing proposal reached max depth and fell back to human review"
FAILURE_BASE_NEXT_TOOLS = ("query.run.status",)
FAILURE_ANALYSIS_NEXT_TOOLS = ("query.run.status", "healing.propose")
FAILURE_FALLBACK_NEXT_TOOLS = ("query.run.status", "query.governance.status")


class FailureProgressReportLike(Protocol):
    failure_fingerprint: str
    healing_attempt_count: int
    fallback_to_human: bool


@dataclass(frozen=True)
class FailureLoopProgressDecision:
    summary: str
    next_tools: list[str]
    assistant_message: str
    planner_kind: str
    fallback_to_human: bool


def failure_loop_summary(*, propose_healing: bool, fallback_to_human: bool) -> str:
    if fallback_to_human:
        return FAILURE_FALLBACK_SUMMARY
    if propose_healing:
        return FAILURE_HEALING_SUMMARY
    return FAILURE_ANALYSIS_SUMMARY


def failure_loop_next_tools(*, propose_healing: bool, fallback_to_human: bool) -> list[str]:
    if fallback_to_human:
        return list(FAILURE_FALLBACK_NEXT_TOOLS)
    if propose_healing:
        return list(FAILURE_BASE_NEXT_TOOLS)
    return list(FAILURE_ANALYSIS_NEXT_TOOLS)


def decide_failure_loop_progress(
    report: FailureProgressReportLike,
    *,
    propose_healing: bool,
    max_healing_depth: int,
) -> FailureLoopProgressDecision:
    summary = failure_loop_summary(
        propose_healing=propose_healing,
        fallback_to_human=report.fallback_to_human,
    )
    return FailureLoopProgressDecision(
        summary=summary,
        next_tools=failure_loop_next_tools(
            propose_healing=propose_healing,
            fallback_to_human=report.fallback_to_human,
        ),
        assistant_message=(
            f"{summary}. Failure fingerprint `{report.failure_fingerprint}` has "
            f"{report.healing_attempt_count}/{max_healing_depth} healing attempts."
        ),
        planner_kind=FAILURE_LOOP_PLANNER_KIND,
        fallback_to_human=report.fallback_to_human,
    )
