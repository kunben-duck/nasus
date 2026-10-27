from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from ..system_image.evidence_tool_models import EvidenceToolReceipt
from ..system_image.image_query_models import ImageQueryReceipt
from ..system_image.build_plan_queries import BuildPlanReadReceipt
from ..system_image.semantic_evaluations import SemanticPreview
from ..quality_loop.acceptance_specifications import AcceptanceAuthorityReceipt
from ..quality_loop.business_rules import BusinessRuleAuthorityReceipt
from ..quality_loop.test_design_scope_inputs import ScopeReceipt
from ..quality_loop.test_design_mapping_inputs import MappingReceipt, PartitionedMappingReceipt
from ..quality_loop.test_design_review_queries import ReviewDraftListReceipt
from ..quality_loop.test_design_generation import GenerationInputReceipt
from ..system_image.context_pack_inputs import ContextPackReceipt, ContextListReceipt, ContextAuthorityBackfillReceipt
from ..system_image.publications import PublicationPreviewReceipt, PublicationHeadReceipt
from ..system_image.code_index_lifecycle import CodeIndexListPage, CodeIndexStatusReceipt, CodeIndexCancelReceipt
from ..system_image.structure_cancel_inputs import StructureCancelReceipt
from ..system_image.investigations import InvestigationReceipt
from ..system_image.build_completions import BuildCompletionReceipt
from ..system_image.gap_ownership import GapOwnershipReceipt


class ToolDefinition(BaseModel):
    tool_id: str
    label: str
    tool_kind: str
    scope: Literal["central", "edge", "either"]
    risk_level: Literal["low", "medium", "high", "critical"]
    confirmation_mode: Literal["none", "user_confirm", "approval_required", "policy_only"]
    description: str
    required_context: List[str] = Field(default_factory=list)
    produced_objects: List[str] = Field(default_factory=list)
    input_schema_ref: Optional[str] = None
    output_schema_ref: Optional[str] = None


class ToolResult(BaseModel):
    invocation_id: str
    status: Literal["completed", "failed", "cancelled"]
    summary: str
    object_refs: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    evidence_query: Optional[EvidenceToolReceipt] = None
    image_query: Optional[ImageQueryReceipt] = None
    build_plan_query: Optional[BuildPlanReadReceipt] = None
    code_index: Optional[Union[CodeIndexListPage, CodeIndexStatusReceipt, CodeIndexCancelReceipt]] = None
    structure_cancel: Optional[StructureCancelReceipt] = None
    investigation: Optional[InvestigationReceipt] = None
    build_completion: Optional[BuildCompletionReceipt] = None
    build_gap_ownership: Optional[GapOwnershipReceipt] = None
    semantic_preview: Optional[SemanticPreview] = None
    index_preview: Optional[Dict[str, Any]] = None
    context_retrieval_preview: Optional[Dict[str, Any]] = None
    context_retrieval_result: Optional[Dict[str, Any]] = None
    test_design_job: Optional[Dict[str, Any]] = None
    test_design_jobs: Optional[Dict[str, Any]] = None
    acceptance_authority: Optional[AcceptanceAuthorityReceipt] = None
    business_rule_authority: Optional[BusinessRuleAuthorityReceipt] = None
    test_design_scope: Optional[ScopeReceipt] = None
    test_design_mapping: Optional[Union[MappingReceipt, PartitionedMappingReceipt]] = None
    test_design_review_drafts: Optional[ReviewDraftListReceipt] = None
    test_design_generation: Optional[GenerationInputReceipt] = None
    test_design_execution_preview: Optional[Dict[str, Any]] = None
    automation_execution_preview: Optional[Dict[str, Any]] = None
    automation_script_history: Optional[Dict[str, Any]] = None
    automation_script_review: Optional[Dict[str, Any]] = None
    run_plan_preview: Optional[Dict[str, Any]] = None
    run_plan_build_preview: Optional[Dict[str, Any]] = None
    run_plan_build: Optional[Dict[str, Any]] = None
    run_plan_observations: Optional[Dict[str, Any]] = None
    run_plan_environment: Optional[Dict[str, Any]] = None
    run_plan_locators: Optional[Dict[str, Any]] = None
    run_plan_locator_record: Optional[Dict[str, Any]] = None
    http_fixture_recipe: Optional[Dict[str, Any]] = None
    http_fixture_grant: Optional[Dict[str, Any]] = None
    http_fixture_job: Optional[Dict[str, Any]] = None
    run_plan_case_job: Optional[Dict[str, Any]] = None
    http_fixture_history: Optional[Dict[str, Any]] = None
    http_fixture_observation: Optional[Dict[str, Any]] = None
    run_plan_environment_record: Optional[Dict[str, Any]] = None
    run_plan_health_record: Optional[Dict[str, Any]] = None
    native_build_preview: Optional[Dict[str, Any]] = None
    native_build_job: Optional[Dict[str, Any]] = None
    context_pack: Optional[Union[ContextPackReceipt, ContextListReceipt]] = None
    context_authority_backfill: Optional[ContextAuthorityBackfillReceipt] = None
    image_publication: Optional[PublicationPreviewReceipt] = None
    image_publication_head: Optional[PublicationHeadReceipt] = None
    requires_followup: bool = False
    followup_reason: Optional[str] = None
    followup_prompt: Optional[str] = None
    next_recommended_tools: List[str] = Field(default_factory=list)


class ToolInvocation(BaseModel):
    id: str
    conversation_id: Optional[str] = None
    tool_id: str
    status: Literal["pending", "running", "waiting_confirmation", "waiting_approval", "completed", "failed", "cancelled"]
    summary: str
    initiator_surface: Literal["chat", "ui", "api", "agent_loop"] = "ui"
    initiator_actor: Literal["user", "agent"] = "user"
    target_scope: Literal["central", "edge"] = "central"
    input_payload: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[ToolResult] = None
    # Runtime coordination fields are durable implementation facts, not part
    # of the public ToolInvocation API contract.
    idempotency_scope: Optional[str] = Field(default=None, exclude=True)
    idempotency_key: Optional[str] = Field(default=None, exclude=True)
    idempotency_fingerprint: Optional[str] = Field(default=None, exclude=True)
    revision: int = Field(default=0, exclude=True)


class AuditEvent(BaseModel):
    id: str
    occurred_at: str
    actor: str
    actor_kind: Literal["user", "agent", "system"] = "system"
    action: str
    entity_type: str
    entity_id: str
    status: Literal[
        "accepted",
        "reviewed",
        "approved",
        "rejected",
        "withdrawn",
        "prepared",
        "build_attested",
        "recorded",
        "issued",
        "reserved",
        "passed",
        "error",
        "timed_out",
        "draft",
        "pending",
        "running",
        "paused",
        "blocked",
        "waiting_confirmation",
        "waiting_approval",
        "completed",
        "failed",
        "cancelled",
    ] = "accepted"
    summary: str
    conversation_id: Optional[str] = None
    tool_invocation_id: Optional[str] = None
    agent_goal_id: Optional[str] = None
    object_refs: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolInvocationRequest(BaseModel):
    conversation_id: Optional[str] = None
    tool_id: str
    input: Dict[str, Any] = Field(default_factory=dict)
    initiator_surface: Literal["chat", "ui", "api", "agent_loop"] = "ui"
    initiator_actor: Literal["user", "agent"] = "user"
    target_scope: Literal["central", "edge"] = "central"
    idempotency_key: Optional[str] = None


class EventPayload(BaseModel):
    event_id: str
    event_type: str
    occurred_at: str
    correlation_id: str
    conversation_id: Optional[str] = None
    tool_invocation_id: Optional[str] = None
    agent_goal_id: Optional[str] = None
    agent_step_id: Optional[str] = None
    swarm_run_id: Optional[str] = None
    assignment_id: Optional[str] = None
    task_id: Optional[str] = None
    run_id: Optional[str] = None
    entity_type: str
    entity_id: str
    entity_version: int
    mutation_kind: Literal["replace", "patch", "append", "invalidate"]
    patch: Dict[str, Any] = Field(default_factory=dict)
    query_keys: List[List[str]] = Field(default_factory=list)
    snapshot_hint: bool = False
    payload: Dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AuditEvent",
    "EventPayload",
    "ToolDefinition",
    "ToolInvocation",
    "ToolInvocationRequest",
    "ToolResult",
]
