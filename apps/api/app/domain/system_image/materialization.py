from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


SYNTHETIC_EVIDENCE_MARKERS = (
    "seeded-fixture",
    "synthetic-fixture",
    "system-image:fallback",
    "source import placeholders",
)


class MaterializedObjectLike(Protocol):
    evidence: list[str]


class MaterializedRelationshipLike(Protocol):
    source_refs: list[str]


class MaterializedMetricLike(Protocol):
    metric_group: str
    evidence_refs: list[str]


@dataclass(frozen=True)
class SystemImageMaterializationDecision:
    ready: bool
    object_count: int
    relationship_count: int
    metric_count: int
    missing_evidence: tuple[str, ...]

    @property
    def summary(self) -> str:
        if self.ready:
            return (
                "source-backed system image evidence is ready: "
                f"objects={self.object_count}, relationships={self.relationship_count}, "
                f"metrics={self.metric_count}"
            )
        return "insufficient source-backed system image evidence: " + ", ".join(
            self.missing_evidence
        )


class InsufficientSystemImageEvidenceError(RuntimeError):
    def __init__(self, decision: SystemImageMaterializationDecision) -> None:
        self.decision = decision
        super().__init__(decision.summary)


def assess_materialized_evidence(
    *,
    objects: Iterable[MaterializedObjectLike],
    relationships: Iterable[MaterializedRelationshipLike],
    metrics: Iterable[MaterializedMetricLike],
) -> SystemImageMaterializationDecision:
    source_backed_objects = [
        item for item in objects if _has_source_backed_refs(item.evidence)
    ]
    source_backed_relationships = [
        item for item in relationships if _has_source_backed_refs(item.source_refs)
    ]
    source_backed_metrics = [
        item for item in metrics if _has_source_backed_refs(item.evidence_refs)
    ]
    has_code_quality = any(
        item.metric_group == "code_quality" for item in source_backed_metrics
    )

    missing: list[str] = []
    if len(source_backed_objects) < 2:
        missing.append("at least one source-derived object in addition to the system root")
    if not source_backed_relationships:
        missing.append("at least one source-derived relationship")
    if not has_code_quality:
        missing.append("a source-derived code_quality metric")

    return SystemImageMaterializationDecision(
        ready=not missing,
        object_count=len(source_backed_objects),
        relationship_count=len(source_backed_relationships),
        metric_count=len(source_backed_metrics),
        missing_evidence=tuple(missing),
    )


def require_materialized_evidence(
    *,
    objects: Iterable[MaterializedObjectLike],
    relationships: Iterable[MaterializedRelationshipLike],
    metrics: Iterable[MaterializedMetricLike],
) -> SystemImageMaterializationDecision:
    decision = assess_materialized_evidence(
        objects=objects,
        relationships=relationships,
        metrics=metrics,
    )
    if not decision.ready:
        raise InsufficientSystemImageEvidenceError(decision)
    return decision


def _has_source_backed_refs(refs: Iterable[str]) -> bool:
    normalized = [str(ref).strip().lower() for ref in refs if str(ref).strip()]
    if not normalized:
        return False
    return not any(
        marker in ref
        for ref in normalized
        for marker in SYNTHETIC_EVIDENCE_MARKERS
    )


__all__ = [
    "InsufficientSystemImageEvidenceError",
    "SYNTHETIC_EVIDENCE_MARKERS",
    "SystemImageMaterializationDecision",
    "assess_materialized_evidence",
    "require_materialized_evidence",
]
