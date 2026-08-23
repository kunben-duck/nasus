from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..quality_loop.quality_models import (
    ApprovalDetail,
    ApprovalSummary,
    AssetLane,
    ReleaseReadiness,
    RunDetail,
    RunSummary,
    USItem,
)
from ..system_image.system_image_models import (
    BaselineRecord,
    ContextRelationship,
    KnowledgeObject,
    QualityMetricSnapshot,
    RawAssetRecord,
)
from .project_models import ProjectCard, VersionSummary
from .read_models import DocumentationEntry


@dataclass(frozen=True)
class DemoSeedSystemImage:
    sources: tuple[RawAssetRecord, ...]
    baselines: tuple[BaselineRecord, ...]
    relationships: tuple[ContextRelationship, ...]
    metric_snapshots: tuple[QualityMetricSnapshot, ...]


@dataclass(frozen=True)
class DemoSeedBaseline:
    project: ProjectCard
    version: VersionSummary
    us_items: tuple[USItem, ...]
    asset_lanes: tuple[AssetLane, ...]
    run_detail: RunDetail
    run_summary: RunSummary
    approval_detail: ApprovalDetail
    approval_summary: ApprovalSummary
    knowledge_objects: tuple[KnowledgeObject, ...]
    system_image: DemoSeedSystemImage
    documentation_entries: tuple[DocumentationEntry, ...]
    release_readiness: ReleaseReadiness


class DemoSeedWorkspacePort(Protocol):
    """Local-only seed persistence and compatibility projection boundary."""

    def seed_baseline(self, baseline: DemoSeedBaseline) -> None: ...

    def ensure_conversation(
        self,
        space_type: str,
        space_id: str,
        title: str,
    ) -> None: ...


__all__ = ["DemoSeedBaseline", "DemoSeedSystemImage", "DemoSeedWorkspacePort"]
