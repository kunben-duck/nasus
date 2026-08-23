from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ConflictEntry(BaseModel):
    path: str
    conflict_kind: Literal["scalar", "object", "array", "text"]
    base_value: Any = None
    left_value: Any = None
    right_value: Any = None
    merge_hint: str
    requires_manual_resolution: bool = True


class MergedResolution(BaseModel):
    """Durable governed fact produced by a structured merge operation."""

    id: str
    project_id: str
    version_id: Optional[str] = None
    task_id: Optional[str] = None
    object_ref: str
    resolution_kind: Literal["structured_3_way"] = "structured_3_way"
    status: Literal["pending_merge", "ready_for_approval", "approved", "rejected"]
    base_ref: Optional[str] = None
    left_candidate_ref: Optional[str] = None
    right_candidate_ref: Optional[str] = None
    base_value: Any = None
    left_candidate: Any = None
    right_candidate: Any = None
    merged_value: Any = None
    auto_merged_patch: List[Dict[str, Any]] = Field(default_factory=list)
    conflict_entries: List[ConflictEntry] = Field(default_factory=list)
    recommended_resolution: str
    merged_from: List[str] = Field(default_factory=list)
    approval_state: Literal["not_requested", "waiting_approval", "approved", "rejected"] = "not_requested"
    approval_ref: Optional[str] = None
    evidence_refs: List[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


__all__ = ["ConflictEntry", "MergedResolution"]
