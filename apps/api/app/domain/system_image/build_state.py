from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Protocol

from .source_binding import REQUIRED_SOURCE_TYPES


class BuildSourceLike(Protocol):
    id: str
    source_type: str
    ingestion_status: str


@dataclass(frozen=True)
class SystemImageBuildStateDecision:
    status: str
    stage_index: int
    label: str
    stage_total: int = 5
    missing_source_types: list[str] = field(default_factory=list)
    failed_source_ids: list[str] = field(default_factory=list)
    next_recommended_tools: list[str] = field(default_factory=list)

    def to_api_kwargs(self) -> dict[str, object]:
        return {
            "status": self.status,
            "stage_index": self.stage_index,
            "stage_total": self.stage_total,
            "label": self.label,
            "missing_source_types": self.missing_source_types,
            "failed_source_ids": self.failed_source_ids,
            "next_recommended_tools": self.next_recommended_tools,
        }


def resolve_build_state(
    *,
    sources: Iterable[BuildSourceLike],
    missing_source_types: list[str],
    has_context: bool,
    has_metrics: bool,
    baseline_status: str | None,
    project_system_image_status: str,
) -> SystemImageBuildStateDecision:
    source_list = list(sources)
    failed_required_sources = [
        source
        for source in source_list
        if source.source_type in REQUIRED_SOURCE_TYPES and source.ingestion_status == "failed"
    ]
    failed_optional_sources = [
        source
        for source in source_list
        if source.source_type not in REQUIRED_SOURCE_TYPES and source.ingestion_status == "failed"
    ]
    if failed_required_sources:
        any_indexed = any(source.ingestion_status == "indexed" for source in source_list)
        return SystemImageBuildStateDecision(
            status="partially_failed" if any_indexed else "failed",
            stage_index=1,
            label="Source ingestion partially failed" if any_indexed else "Source ingestion failed",
            failed_source_ids=[source.id for source in failed_required_sources],
            next_recommended_tools=["system_image.sources.register", "system_image.sources.ingest"],
        )

    if missing_source_types:
        return SystemImageBuildStateDecision(
            status="source_required",
            stage_index=0,
            label="Source bindings required",
            missing_source_types=missing_source_types,
            next_recommended_tools=["system_image.sources.register"],
        )

    required_sources = [
        source
        for source in source_list
        if source.source_type in REQUIRED_SOURCE_TYPES
    ]
    all_required_sources_indexed = bool(required_sources) and all(
        source.ingestion_status == "indexed"
        for source in required_sources
    )
    any_ingesting = any(source.ingestion_status == "ingesting" for source in source_list)
    any_pending = any(source.ingestion_status == "pending" for source in source_list)
    baseline_ready = baseline_status in {"ready", "promoted"}
    optional_failure_ids = [source.id for source in failed_optional_sources]

    if baseline_ready and project_system_image_status == "ready":
        return SystemImageBuildStateDecision(
            status="ready",
            stage_index=5,
            label=(
                "Official System Image ready with optional source gaps"
                if optional_failure_ids
                else "Official System Image ready"
            ),
            failed_source_ids=optional_failure_ids,
            next_recommended_tools=["query.system_image.status", "version.create", "quality.scenario.generate"],
        )
    if has_context and has_metrics:
        return SystemImageBuildStateDecision(
            status="materialized",
            stage_index=4,
            label=(
                "Context materialized with optional source gaps, waiting for baseline promotion"
                if optional_failure_ids
                else "Context materialized, waiting for baseline promotion"
            ),
            failed_source_ids=optional_failure_ids,
            next_recommended_tools=["system_image.baseline.initialize"],
        )
    if any_ingesting:
        return SystemImageBuildStateDecision(
            status="ingesting",
            stage_index=2,
            label="Source ingestion in progress",
            failed_source_ids=optional_failure_ids,
            next_recommended_tools=[],
        )
    if any_pending:
        return SystemImageBuildStateDecision(
            status="sources_registered",
            stage_index=2,
            label="Sources registered, ingestion pending",
            failed_source_ids=optional_failure_ids,
            next_recommended_tools=["system_image.sources.ingest"],
        )
    if all_required_sources_indexed:
        return SystemImageBuildStateDecision(
            status="indexed",
            stage_index=3,
            label=(
                "Required sources indexed with optional source gaps"
                if optional_failure_ids
                else "Sources indexed, context not materialized"
            ),
            failed_source_ids=optional_failure_ids,
            next_recommended_tools=["system_image.context.materialize"],
        )
    return SystemImageBuildStateDecision(
        status="sources_registered",
        stage_index=2,
        label="Sources registered, ingestion pending",
        next_recommended_tools=["system_image.sources.ingest"],
    )
