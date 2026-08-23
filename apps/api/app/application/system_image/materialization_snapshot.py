from __future__ import annotations

from dataclasses import dataclass

from ..platform.project_models import ProjectCard
from ..quality_loop.quality_models import AssetLane, USItem
from .system_image_models import (
    BaselineRecord,
    ContextRelationship,
    EmbeddingRecord,
    KnowledgeObject,
    QualityMetricSnapshot,
    QualityProfile,
    RawAssetChunk,
    RerankRecord,
    RetrievalRun,
    TaskContext,
)


@dataclass(frozen=True)
class SystemImageMaterializationSnapshot:
    project: ProjectCard
    version_id: str | None
    chunks: list[RawAssetChunk]
    objects: list[KnowledgeObject]
    relationships: list[ContextRelationship]
    metrics: list[QualityMetricSnapshot]
    baselines: list[BaselineRecord]
    embeddings: list[EmbeddingRecord]
    retrieval_runs: list[RetrievalRun]
    rerank_records: list[RerankRecord]
    task_contexts: list[TaskContext]
    quality_profiles: list[QualityProfile]
    us_items: list[USItem]
    asset_lanes: dict[str, list[AssetLane]]


__all__ = ["SystemImageMaterializationSnapshot"]
