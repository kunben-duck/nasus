from __future__ import annotations

from hashlib import sha256
from typing import Any, Iterable, Mapping, Protocol


REQUIRED_QUALITY_SOURCE_TYPES = ("code",)


class QualitySourceLike(Protocol):
    source_type: str
    ingestion_status: str


class RelationshipLike(Protocol):
    pass


class MetricLike(Protocol):
    metric_group: str
    metrics: Mapping[str, Any]


def missing_quality_context(sources: Iterable[QualitySourceLike], us_id: str | None) -> list[str]:
    indexed_source_types = {
        source.source_type
        for source in sources
        if source.ingestion_status == "indexed"
    }
    missing = [
        expected
        for expected in REQUIRED_QUALITY_SOURCE_TYPES
        if expected not in indexed_source_types
    ]
    if us_id is None:
        missing.append("us_work_item")
    return missing


def context_hash(
    project_id: str,
    baseline_id: str,
    target_id: str,
    source_refs: list[str],
    chunk_refs: list[str],
    object_refs: list[str],
    relationship_refs: list[str],
    metric_refs: list[str],
) -> str:
    payload = "|".join([
        project_id,
        baseline_id,
        target_id,
        ",".join(source_refs),
        ",".join(chunk_refs),
        ",".join(object_refs),
        ",".join(relationship_refs),
        ",".join(metric_refs),
    ])
    return sha256(payload.encode("utf-8")).hexdigest()


def context_confidence(
    sources: Iterable[QualitySourceLike],
    relationships: Iterable[RelationshipLike],
    metrics: Iterable[MetricLike],
) -> float:
    indexed_source_types = {
        source.source_type
        for source in sources
        if source.ingestion_status == "indexed"
    }
    indexed_source_score = (
        (0.6 if "code" in indexed_source_types else 0.0)
        + (0.2 if "us_doc" in indexed_source_types else 0.0)
        + (0.2 if "test_asset" in indexed_source_types else 0.0)
    )
    relationship_score = min(1.0, len(list(relationships)) / 6)
    metric_score = min(1.0, len(list(metrics)) / 3)
    return round(max(0.0, min(1.0, indexed_source_score * 0.4 + relationship_score * 0.3 + metric_score * 0.3)), 2)


def risk_score(metrics: Iterable[MetricLike]) -> int:
    metric_list = list(metrics)
    code = _metric_by_group(metric_list, "code_quality")
    tests = _metric_by_group(metric_list, "test_quality")
    code_risk = int((code.metrics.get("code_risk_score", 50) if code else 50))
    failed_runs = int((tests.metrics.get("failed_runs", 0) if tests else 0))
    return min(100, max(0, code_risk + failed_runs * 8))


def coverage_score(metrics: Iterable[MetricLike]) -> int:
    tests = _metric_by_group(list(metrics), "test_quality")
    scenario = float((tests.metrics.get("scenario_coverage", 0) if tests else 0) or 0)
    automation = float((tests.metrics.get("automation_coverage", 0) if tests else 0) or 0)
    return min(100, max(0, round(((scenario * 0.6) + (automation * 0.4)) * 100)))


def automation_feasibility(metrics: Iterable[MetricLike]) -> int:
    tests = _metric_by_group(list(metrics), "test_quality")
    automation = float((tests.metrics.get("automation_coverage", 0) if tests else 0) or 0)
    test_count = int((tests.metrics.get("test_count", 0) if tests else 0) or 0)
    return min(100, max(0, round(automation * 80 + min(test_count, 5) * 4)))


def release_score(metrics: Iterable[MetricLike], *, blocked_items: int, pending_approvals: int) -> int:
    metric_list = list(metrics)
    release = _metric_by_group(metric_list, "release_readiness")
    if release and "release_score" in release.metrics:
        return int(release.metrics["release_score"])
    coverage = coverage_score(metric_list)
    risk = risk_score(metric_list)
    blocker_penalty = blocked_items * 8 + pending_approvals * 4
    return min(100, max(0, round(coverage * 0.7 + (100 - risk) * 0.3 - blocker_penalty)))


def risk_drivers(metrics: Iterable[MetricLike], relationships: Iterable[RelationshipLike]) -> list[str]:
    metric_list = list(metrics)
    relationship_list = list(relationships)
    drivers: list[str] = []
    code = _metric_by_group(metric_list, "code_quality")
    tests = _metric_by_group(metric_list, "test_quality")
    us = _metric_by_group(metric_list, "us_completion_quality")
    if code and int(code.metrics.get("code_risk_score", 0)) >= 60:
        drivers.append("Code risk score is elevated for changed or critical modules.")
    if tests and float(tests.metrics.get("automation_coverage", 0) or 0) < 0.6:
        drivers.append("Automation coverage is below the release confidence threshold.")
    if us and float(us.metrics.get("acceptance_criteria_coverage", us.metrics.get("requirements_clarity", 1)) or 0) < 0.8:
        drivers.append("US acceptance criteria or requirement clarity needs review.")
    if len(relationship_list) < 3:
        drivers.append("Context relationship graph is still sparse.")
    return drivers or ["No dominant risk driver detected from current system image metrics."]


def _metric_by_group(metrics: Iterable[MetricLike], group: str) -> MetricLike | None:
    return next((metric for metric in metrics if metric.metric_group == group), None)
