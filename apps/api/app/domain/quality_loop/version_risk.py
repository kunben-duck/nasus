from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


VALID_RISK_LEVELS = {"high", "medium", "low"}
HIGH_RISK_STATUSES = {"blocked", "execution_failed"}
DEFAULT_QUALITY_LOOP_NEXT_ACTION = "Start quality loop"
MEDIUM_RISK_PROGRESS_THRESHOLD = 60
HIGH_RISK_PROGRESS_THRESHOLD = 20
PROJECT_PROGRESS_FLOOR_AFTER_RISK_INIT = 34


class USWorkItemLike(Protocol):
    """Minimal US work-item shape required by the version risk policy."""

    id: str
    status: str
    risk: str
    progress: int
    next_action: str


@dataclass(frozen=True)
class USRiskDecision:
    us_id: str
    risk: str
    next_action: str


@dataclass(frozen=True)
class VersionRiskDecision:
    item_decisions: list[USRiskDecision]
    high_count: int
    medium_count: int
    project_risk: str
    project_progress_floor: int
    summary: str


def decide_us_risk(item: USWorkItemLike) -> USRiskDecision:
    risk = item.risk
    if item.status in HIGH_RISK_STATUSES or item.progress < HIGH_RISK_PROGRESS_THRESHOLD:
        risk = "high"
    elif item.progress < MEDIUM_RISK_PROGRESS_THRESHOLD:
        risk = "medium"
    elif risk not in VALID_RISK_LEVELS:
        risk = "low"

    return USRiskDecision(
        us_id=item.id,
        risk=risk,
        next_action=item.next_action or DEFAULT_QUALITY_LOOP_NEXT_ACTION,
    )


def decide_version_risk(items: list[USWorkItemLike]) -> VersionRiskDecision:
    item_decisions = [decide_us_risk(item) for item in items]
    high_count = sum(1 for item in item_decisions if item.risk == "high")
    medium_count = sum(1 for item in item_decisions if item.risk == "medium")
    project_risk = "high" if high_count else ("medium" if medium_count else "low")

    return VersionRiskDecision(
        item_decisions=item_decisions,
        high_count=high_count,
        medium_count=medium_count,
        project_risk=project_risk,
        project_progress_floor=PROJECT_PROGRESS_FLOOR_AFTER_RISK_INIT,
        summary=f"Initialized version risk: {high_count} high-risk and {medium_count} medium-risk US item(s).",
    )
