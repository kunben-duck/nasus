from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class USItem(BaseModel):
    id: str
    title: str
    owner: str
    status: str
    risk: str
    progress: int
    next_action: str


class AssetLane(BaseModel):
    id: str
    label: str
    status: str
    summary: str
    updated_at: str


class QualityAssetGenerationMetadata(BaseModel):
    prompt_id: str
    prompt_version: str
    provider: str
    model_name: str
    mode: Literal["live", "fallback"]
    reason: str
    input_context_hash: str
    generated_at: str


class QualityAssetPart(BaseModel):
    id: str
    part_type: Literal[
        "scope_pack",
        "scenario_set",
        "verification_plan",
        "case_set",
        "automation_blueprint",
        "change_document",
        "release_assessment",
    ]
    status: Literal["draft", "ready_for_review", "approved", "completed", "blocked"]
    title: str
    summary: str
    revision: int = 1
    object_refs: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    structured_content: Dict[str, Any] = Field(default_factory=dict)
    generation: Optional[QualityAssetGenerationMetadata] = None
    updated_at: str


class QualityAssetPack(BaseModel):
    id: str
    project_id: str
    version_id: Optional[str] = None
    us_id: str
    status: Literal["draft", "in_review", "approved", "completed", "pending_merge", "blocked"] = "draft"
    current_revision: int = 1
    parts: List[QualityAssetPart] = Field(default_factory=list)
    source_refs: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    updated_at: str


class RunSummary(BaseModel):
    id: str
    status: str
    channel: Literal["web_runner"]
    title: str
    summary: str
    started_at: str


class RunDetail(RunSummary):
    task_context_id: Optional[str] = None
    runner_job_id: Optional[str] = None
    timeline: List[str] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)
    failure_summary: str
    healing_status: str
    healing_depth: int = 0
    last_failure_fingerprint: Optional[str] = None
    us_id: Optional[str] = None
    target_base_url: Optional[str] = None
    automation_asset_ref: Optional[str] = None
    automation_script_id: Optional[str] = None
    execution_plan: List[Dict[str, Any]] = Field(default_factory=list)
    execution_timeout_ms: int = 60_000
    retry_of_run_id: Optional[str] = None
    attempt: int = 1


class ExecutionEvidence(BaseModel):
    id: str
    project_id: str
    run_id: str
    us_id: Optional[str] = None
    case_ref: Optional[str] = None
    evidence_type: Literal["script", "trace", "log", "screenshot", "video", "report", "failure_artifact"]
    storage_ref: str
    content_hash: str
    producer: Literal["agent", "web_runner", "system"] = "system"
    captured_at: str
    redaction_status: Literal["not_required", "pending", "redacted"] = "not_required"
    retention_policy: str = "project_default"


class FailureReport(BaseModel):
    id: str
    project_id: str
    run_id: str
    us_id: Optional[str] = None
    failure_kind: Literal["assertion", "selector", "environment", "data", "network", "timeout", "unknown"]
    failure_fingerprint: str
    summary: str
    root_cause: str
    evidence_refs: List[str] = Field(default_factory=list)
    status: Literal["open", "under_review", "healing_proposed", "fallback_to_human", "resolved", "closed"] = "open"
    healing_attempt_count: int = 0
    fallback_to_human: bool = False
    cooldown_until: Optional[str] = None
    created_at: str


class ReleaseDecision(BaseModel):
    id: str
    project_id: str
    version_id: str
    us_id: Optional[str] = None
    status: Literal["ready", "conditional", "blocked", "needs_evidence"]
    score: int = Field(ge=0, le=100)
    rationale: str
    evidence_refs: List[str] = Field(default_factory=list)
    approval_ref: Optional[str] = None
    created_at: str


class ApprovalSummary(BaseModel):
    id: str
    title: str
    status: str
    summary: str


class ApprovalDetail(ApprovalSummary):
    policy_reason: str
    conflict_fields: List[str] = Field(default_factory=list)
    recommended_resolution: str
    evidence: List[str] = Field(default_factory=list)


class ReleaseReadiness(BaseModel):
    version_id: str
    status: str
    score: int
    blockers: int
    approvals_open: int
    pending_merge: int
    execution_health: str
    summary: str
    blocker_items: List[str] = Field(default_factory=list)
    score_breakdown: Dict[str, int] = Field(default_factory=dict)
    evidence_summary: Dict[str, int] = Field(default_factory=dict)


class QualityLoopState(BaseModel):
    status: Literal["no_us", "not_started", "in_progress", "ready_for_release", "blocked"]
    stage_index: int
    stage_total: int = 6
    label: str
    release_score: int = 0
    next_recommended_tools: List[str] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)


__all__ = [
    "ApprovalDetail",
    "ApprovalSummary",
    "AssetLane",
    "ExecutionEvidence",
    "FailureReport",
    "QualityAssetPack",
    "QualityAssetGenerationMetadata",
    "QualityAssetPart",
    "QualityLoopState",
    "ReleaseDecision",
    "ReleaseReadiness",
    "RunDetail",
    "RunSummary",
    "USItem",
]
