from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ..platform.model_settings import ProviderName
from ..platform.project_models import ProjectCard


class KnowledgeObject(BaseModel):
    id: str
    name: str
    type: str
    branch: str
    confidence: str
    relations: List[str] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)
    freshness: str


class RawAssetRecord(BaseModel):
    id: str
    project_id: str
    version_id: Optional[str] = None
    source_type: Literal["code", "us_doc", "test_asset"]
    source_uri: str
    source_label: Optional[str] = None
    ingestion_status: Literal["pending", "ingesting", "indexed", "failed", "stale"] = "pending"
    content_hash: str = ""
    content_ref: Optional[str] = None
    evidence_refs: List[str] = Field(default_factory=list)
    registered_at: Optional[str] = None
    registered_by_actor: Literal["user", "agent", "system"] = "system"
    registered_from_invocation_id: Optional[str] = None
    credential_ref: Optional[str] = None
    permission_status: Literal["not_checked", "allowed", "denied"] = "not_checked"
    permission_checked_at: Optional[str] = None
    ingest_started_at: Optional[str] = None
    last_ingested_at: Optional[str] = None
    failure_reason: Optional[str] = None
    file_count: int = 0
    byte_count: int = 0


class RawAssetChunk(BaseModel):
    id: str
    project_id: str
    raw_asset_id: str
    source_type: Literal["code", "us_doc", "test_asset"]
    chunk_kind: Literal["code", "requirement", "test", "summary"]
    section_path: str
    content_ref: str
    content_hash: str
    token_estimate: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    embedding_record_id: Optional[str] = None
    created_at: str


class BaselineRecord(BaseModel):
    id: str
    project_id: str
    kind: Literal["official", "version_working", "version_shared"]
    status: Literal["draft", "building", "ready", "stale", "pending_merge", "promoted"]
    source_version_id: Optional[str] = None
    parent_baseline_id: Optional[str] = None
    fork_strategy: Literal["copy_on_write", "materialized_snapshot"] = "copy_on_write"
    object_count: int = 0
    relationship_count: int = 0
    metric_snapshot_count: int = 0
    updated_at: str


class ContextRelationship(BaseModel):
    id: str
    project_id: str
    baseline_id: str
    from_object_id: str
    relationship_type: Literal[
        "implements",
        "depends_on",
        "covers",
        "validates",
        "impacts",
        "evidenced_by",
        "belongs_to",
    ]
    to_object_id: str
    confidence: float = Field(ge=0, le=1)
    source_refs: List[str] = Field(default_factory=list)


class ContextObjectOverlay(BaseModel):
    id: str
    project_id: str
    baseline_id: str
    object_id: str
    field_path: str
    operation: Literal["add", "replace", "remove"]
    value_ref: Optional[str] = None
    source_refs: List[str] = Field(default_factory=list)
    status: Literal["candidate", "merged", "rejected"] = "candidate"


class QualityMetricSnapshot(BaseModel):
    id: str
    project_id: str
    baseline_id: str
    version_id: Optional[str] = None
    us_id: Optional[str] = None
    task_id: Optional[str] = None
    metric_group: Literal["code_quality", "us_completion_quality", "test_quality", "release_readiness"]
    metrics: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[str] = Field(default_factory=list)
    captured_at: str


class EmbeddingRecord(BaseModel):
    id: str
    project_id: str
    baseline_id: str
    source_ref: Optional[str] = None
    object_ref: Optional[str] = None
    chunk_ref: Optional[str] = None
    content_hash: str
    embedding_model: str
    embedding_version: str = "settings.current"
    provider: ProviderName
    vector_ref: str
    dimensions: int = 0
    embedding_vector: List[float] = Field(default_factory=list, exclude=True, repr=False)
    search_text: str = Field(default="", exclude=True, repr=False)
    status: Literal["ready", "fallback", "stale", "failed", "excluded"]
    fallback_reason: Optional[str] = None
    created_at: str


class RetrievalRun(BaseModel):
    id: str
    project_id: str
    baseline_id: str
    version_id: Optional[str] = None
    us_id: Optional[str] = None
    query: str
    strategy: Literal["hybrid_graph_vector", "rule_based_fusion"]
    candidate_count: int = 0
    result_refs: List[str] = Field(default_factory=list)
    embedding_record_ids: List[str] = Field(default_factory=list)
    rerank_record_id: Optional[str] = None
    fallback_used: bool = False
    created_at: str


class RerankRecord(BaseModel):
    id: str
    project_id: str
    retrieval_run_id: str
    rerank_model: str
    rerank_version: str
    input_count: int = 0
    output_count: int = 0
    status: Literal["completed", "fallback", "skipped", "failed"]
    latency_ms: int = 0
    fallback_reason: Optional[str] = None
    created_at: str


class TaskContext(BaseModel):
    id: str
    project_id: str
    baseline_id: str
    version_id: Optional[str] = None
    us_id: Optional[str] = None
    retrieval_run_id: str
    summary: str
    readiness: Literal["ready", "stale", "blocked"]
    source_refs: List[str] = Field(default_factory=list)
    object_refs: List[str] = Field(default_factory=list)
    relationship_refs: List[str] = Field(default_factory=list)
    metric_refs: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    missing_context: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)
    freshness_at: str
    context_hash: str


class QualityProfile(BaseModel):
    id: str
    project_id: str
    baseline_id: str
    version_id: Optional[str] = None
    us_id: Optional[str] = None
    task_context_id: str
    risk_score: int = Field(ge=0, le=100)
    coverage_score: int = Field(ge=0, le=100)
    release_score: int = Field(ge=0, le=100)
    automation_feasibility: int = Field(ge=0, le=100)
    risk_drivers: List[str] = Field(default_factory=list)
    regression_scope_refs: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)
    freshness_at: str


class SystemImageBuildState(BaseModel):
    status: Literal[
        "source_required",
        "sources_registered",
        "ingesting",
        "indexed",
        "materialized",
        "ready",
        "partially_failed",
        "failed",
    ]
    stage_index: int
    stage_total: int = 5
    label: str
    missing_source_types: List[str] = Field(default_factory=list)
    failed_source_ids: List[str] = Field(default_factory=list)
    next_recommended_tools: List[str] = Field(default_factory=list)


class SystemImageResponse(BaseModel):
    project: ProjectCard
    summary: str
    build_state: SystemImageBuildState
    baselines: List[BaselineRecord]
    sources: List[RawAssetRecord]
    chunks: List[RawAssetChunk] = Field(default_factory=list)
    objects: List[KnowledgeObject]
    relationships: List[ContextRelationship]
    overlays: List[ContextObjectOverlay]
    metric_snapshots: List[QualityMetricSnapshot]
    embedding_records: List[EmbeddingRecord] = Field(default_factory=list)
    retrieval_runs: List[RetrievalRun] = Field(default_factory=list)
    rerank_records: List[RerankRecord] = Field(default_factory=list)
    task_contexts: List[TaskContext] = Field(default_factory=list)
    quality_profiles: List[QualityProfile] = Field(default_factory=list)


__all__ = [
    "BaselineRecord",
    "ContextObjectOverlay",
    "ContextRelationship",
    "EmbeddingRecord",
    "KnowledgeObject",
    "QualityMetricSnapshot",
    "QualityProfile",
    "RawAssetChunk",
    "RawAssetRecord",
    "RerankRecord",
    "RetrievalRun",
    "SystemImageBuildState",
    "SystemImageResponse",
    "TaskContext",
]
