from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Dict, List, Literal, Optional, Protocol, Type, Union

from pydantic import BaseModel, Field, model_validator

from ..platform.prompts import PromptRegistryPort
from ...domain.platform.prompt_registry import builtin_prompt
from .quality_models import QualityAssetGenerationMetadata


QualityGenerationStage = Literal[
    "scope",
    "scenarios",
    "verification_plan",
    "cases",
    "automation",
    "change_document",
]


class QualityScopeTarget(BaseModel):
    target_id: str
    title: str
    reason: str
    linked_context_objects: List[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high", "critical"] = "medium"


class QualityScopeOutput(BaseModel):
    in_scope: List[QualityScopeTarget] = Field(min_length=1)
    out_of_scope: List[QualityScopeTarget] = Field(default_factory=list)
    regression_targets: List[QualityScopeTarget] = Field(default_factory=list)
    risk_targets: List[QualityScopeTarget] = Field(default_factory=list)


class QualityScenario(BaseModel):
    scenario_id: str
    title: str
    category: Literal[
        "main_flow",
        "branch",
        "error_path",
        "permission",
        "compatibility_regression",
        "boundary_data",
        "observability",
    ]
    objective: str
    preconditions: List[str] = Field(default_factory=list)
    linked_context_objects: List[str] = Field(default_factory=list)
    risk_reason: str


class QualityScenarioOutput(BaseModel):
    scenarios: List[QualityScenario] = Field(min_length=1)


class VerificationPriority(BaseModel):
    priority_id: str
    title: str
    priority: Literal["P0", "P1", "P2", "P3"]
    scenario_ids: List[str] = Field(default_factory=list)
    reason: str


class VerificationExecutionAllocation(BaseModel):
    scenario_id: str
    execution_mode: Literal["manual", "automation", "hybrid"]
    reason: str


class VerificationApprovalPoint(BaseModel):
    approval_id: str
    title: str
    required_role: Literal["qa", "qa_lead", "developer", "project_manager", "administrator"]
    condition: str


class VerificationPlanOutput(BaseModel):
    priorities: List[VerificationPriority] = Field(min_length=1)
    environment_requirements: List[str] = Field(default_factory=list)
    data_requirements: List[str] = Field(default_factory=list)
    execution_allocations: List[VerificationExecutionAllocation] = Field(min_length=1)
    performance_requirements: List[str] = Field(default_factory=list)
    approval_points: List[VerificationApprovalPoint] = Field(default_factory=list)


class QualityCaseStep(BaseModel):
    action: str
    expected_result: str


class QualityTestCase(BaseModel):
    case_id: str
    scenario_id: str
    title: str
    preconditions: List[str] = Field(default_factory=list)
    steps: List[QualityCaseStep] = Field(min_length=1)
    expected_results: List[str] = Field(min_length=1)
    test_data_hint: str
    assertion_type: Literal["ui", "api", "data", "event", "integration", "security"]
    priority: Literal["P0", "P1", "P2", "P3"]
    regression_tags: List[str] = Field(default_factory=list)


class QualityCaseOutput(BaseModel):
    cases: List[QualityTestCase] = Field(min_length=1)


class AutomationStep(BaseModel):
    action: Literal[
        "goto",
        "click",
        "fill",
        "press",
        "assert_text",
        "assert_visible",
        "assert_url",
        "wait_for",
    ]
    selector: Optional[str] = None
    value: Optional[str] = None
    text: Optional[str] = None
    path: Optional[str] = None
    key: Optional[str] = None
    state: Optional[Literal["attached", "detached", "visible", "hidden"]] = None
    timeout_ms: Optional[int] = Field(default=None, ge=100, le=30_000)

    @model_validator(mode="after")
    def validate_action_fields(self) -> "AutomationStep":
        requirements = {
            "goto": ("path",),
            "click": ("selector",),
            "fill": ("selector", "value"),
            "press": ("selector", "key"),
            "assert_text": ("text",),
            "assert_visible": ("selector",),
            "assert_url": ("value",),
            "wait_for": ("selector",),
        }
        missing = [
            field_name
            for field_name in requirements[self.action]
            if getattr(self, field_name) is None
        ]
        if missing:
            raise ValueError(
                f"{self.action} requires field(s): {', '.join(missing)}"
            )
        return self


class AutomationScript(BaseModel):
    script_id: str
    title: str
    linked_case_ids: List[str] = Field(min_length=1)
    steps: List[AutomationStep] = Field(min_length=1, max_length=100)
    timeout_ms: int = Field(default=60_000, ge=1_000, le=120_000)


class AutomationBlueprintOutput(BaseModel):
    framework: Literal["playwright"] = "playwright"
    default_base_url: Optional[str] = None
    scripts: List[AutomationScript] = Field(min_length=1)
    selector_strategy: str
    fixture_hints: List[str] = Field(default_factory=list)


class QualityChangeDelta(BaseModel):
    delta_id: str
    source_type: Literal["requirement", "code", "system_image", "test_asset"]
    summary: str
    object_refs: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)


class QualityChangeRisk(BaseModel):
    risk_id: str
    title: str
    severity: Literal["low", "medium", "high", "critical"]
    rationale: str
    verification_refs: List[str] = Field(default_factory=list)


class QualityChangeDocumentOutput(BaseModel):
    document_id: str
    title: str
    executive_summary: str
    deltas: List[QualityChangeDelta] = Field(min_length=1)
    scope_summary: str
    scenario_summary: str
    case_summary: str
    risks: List[QualityChangeRisk] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    unresolved_questions: List[str] = Field(default_factory=list)


QualityGenerationOutput = Union[
    QualityScopeOutput,
    QualityScenarioOutput,
    VerificationPlanOutput,
    QualityCaseOutput,
    AutomationBlueprintOutput,
    QualityChangeDocumentOutput,
]


class QualityGenerationRequest(BaseModel):
    stage: QualityGenerationStage
    project_id: str
    us_id: str
    task_context: Dict[str, Any]
    quality_profile: Dict[str, Any]
    prior_assets: List[Dict[str, Any]] = Field(default_factory=list)
    tool_input: Dict[str, Any] = Field(default_factory=dict)
    conversation_id: Optional[str] = None
    agent_goal_id: Optional[str] = None
    tool_invocation_id: Optional[str] = None

    def input_context_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"


class QualityGenerationResult(BaseModel):
    stage: QualityGenerationStage
    title: str
    summary: str
    structured_output: Dict[str, Any]
    generation: QualityAssetGenerationMetadata


class QualityGenerationError(RuntimeError):
    pass


class QualityGenerationPort(Protocol):
    async def generate(self, request: QualityGenerationRequest) -> QualityGenerationResult:
        """Generate and validate one quality asset part without mutating domain state."""


class DeterministicQualityGenerationAdapter:
    """Explicit offline adapter used by isolated domain/application tests."""

    async def generate(self, request: QualityGenerationRequest) -> QualityGenerationResult:
        prompt = prompt_for_stage(request.stage)
        payload = fallback_generation_output(
            request.stage,
            request.us_id,
            tool_input=request.tool_input,
        )
        return QualityGenerationResult(
            stage=request.stage,
            title=generation_title(request.stage),
            summary=generation_summary(request.stage, payload),
            structured_output=payload,
            generation=QualityAssetGenerationMetadata(
                prompt_id=prompt.prompt_id,
                prompt_version=prompt.prompt_version,
                provider="mock",
                model_name="nasus-deterministic-quality-fallback",
                mode="fallback",
                reason="offline_application_adapter",
                input_context_hash=request.input_context_hash(),
                generated_at=datetime.now(timezone.utc).isoformat(),
            ),
        )


class QualityPromptDefinition(BaseModel):
    prompt_id: str
    prompt_version: str
    output_schema_ref: str
    system_prompt: str


QUALITY_PROMPT_IDS: dict[QualityGenerationStage, str] = {
    "scope": "quality.scope.generate",
    "scenarios": "quality.scenario.generate",
    "verification_plan": "quality.plan.generate",
    "cases": "quality.case.generate",
    "automation": "automation.generate",
    "change_document": "quality.change-doc.generate",
}


def _quality_prompt_from_definition(definition: Any) -> QualityPromptDefinition:
    return QualityPromptDefinition(
        prompt_id=definition.prompt_id,
        prompt_version=definition.version,
        output_schema_ref=definition.output_schema_ref,
        system_prompt=definition.system_template,
    )


QUALITY_GENERATION_PROMPTS: dict[QualityGenerationStage, QualityPromptDefinition] = {
    stage: _quality_prompt_from_definition(builtin_prompt(prompt_id))
    for stage, prompt_id in QUALITY_PROMPT_IDS.items()
}


def prompt_for_stage(
    stage: QualityGenerationStage,
    registry: PromptRegistryPort | None = None,
) -> QualityPromptDefinition:
    definition = (
        registry.get_active(QUALITY_PROMPT_IDS[stage])
        if registry is not None
        else builtin_prompt(QUALITY_PROMPT_IDS[stage])
    )
    return _quality_prompt_from_definition(definition)


def output_model_for_stage(stage: QualityGenerationStage) -> Type[BaseModel]:
    return {
        "scope": QualityScopeOutput,
        "scenarios": QualityScenarioOutput,
        "verification_plan": VerificationPlanOutput,
        "cases": QualityCaseOutput,
        "automation": AutomationBlueprintOutput,
        "change_document": QualityChangeDocumentOutput,
    }[stage]


def validate_generation_output(stage: QualityGenerationStage, payload: Dict[str, Any]) -> Dict[str, Any]:
    return output_model_for_stage(stage).model_validate(payload).model_dump(mode="json")


def fallback_generation_output(
    stage: QualityGenerationStage,
    us_id: str,
    *,
    tool_input: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    if stage == "scope":
        return QualityScopeOutput(
            in_scope=[
                QualityScopeTarget(
                    target_id=f"scope_{us_id}_core",
                    title="Core user journey",
                    reason="Primary behavior linked to the current US and task context.",
                    linked_context_objects=[f"us:{us_id}"],
                    risk_level="high",
                ),
                QualityScopeTarget(
                    target_id=f"scope_{us_id}_integration",
                    title="Integration boundaries",
                    reason="Validate system-image relationships touched by the change.",
                    linked_context_objects=[f"us:{us_id}"],
                ),
            ],
            regression_targets=[
                QualityScopeTarget(
                    target_id=f"scope_{us_id}_regression",
                    title="Related regression paths",
                    reason="Protect existing behavior adjacent to the changed capability.",
                    linked_context_objects=[f"us:{us_id}"],
                )
            ],
            risk_targets=[
                QualityScopeTarget(
                    target_id=f"scope_{us_id}_failure",
                    title="Failure and recovery behavior",
                    reason="Exercise validation, failure handling, and observability paths.",
                    linked_context_objects=[f"us:{us_id}"],
                    risk_level="high",
                )
            ],
        ).model_dump(mode="json")
    if stage == "scenarios":
        categories = [
            ("main_flow", "Complete the primary user journey"),
            ("branch", "Exercise a supported business branch"),
            ("error_path", "Reject an invalid or failed operation safely"),
            ("permission", "Enforce actor permissions"),
            ("compatibility_regression", "Protect related existing behavior"),
            ("boundary_data", "Handle boundary and malformed data"),
            ("observability", "Emit actionable operational evidence"),
        ]
        return QualityScenarioOutput(
            scenarios=[
                QualityScenario(
                    scenario_id=f"scenario_{us_id}_{index + 1}",
                    title=title,
                    category=category,  # type: ignore[arg-type]
                    objective=title,
                    preconditions=["The current version context is materialized."],
                    linked_context_objects=[f"us:{us_id}"],
                    risk_reason="Deterministic local fallback; review against live system-image evidence.",
                )
                for index, (category, title) in enumerate(categories)
            ]
        ).model_dump(mode="json")

    if stage == "verification_plan":
        return VerificationPlanOutput(
            priorities=[
                VerificationPriority(
                    priority_id=f"priority_{us_id}_critical",
                    title="Release-critical behavior",
                    priority="P0",
                    scenario_ids=[f"scenario_{us_id}_1", f"scenario_{us_id}_3"],
                    reason="Primary and failure paths must pass before release review.",
                ),
                VerificationPriority(
                    priority_id=f"priority_{us_id}_regression",
                    title="Regression and boundary coverage",
                    priority="P1",
                    scenario_ids=[f"scenario_{us_id}_5", f"scenario_{us_id}_6"],
                    reason="Adjacent behavior and boundary data require explicit evidence.",
                ),
            ],
            environment_requirements=[
                "A revision-pinned deployment that matches the active version branch.",
                "Access to logs, traces, and test evidence storage.",
            ],
            data_requirements=[
                "A deterministic happy-path account and representative business data.",
                "Boundary and invalid data for negative-path verification.",
            ],
            execution_allocations=[
                VerificationExecutionAllocation(
                    scenario_id=f"scenario_{us_id}_1",
                    execution_mode="automation",
                    reason="The primary flow is stable and release critical.",
                ),
                VerificationExecutionAllocation(
                    scenario_id=f"scenario_{us_id}_4",
                    execution_mode="hybrid",
                    reason="Permission behavior needs automated checks and human policy review.",
                ),
            ],
            performance_requirements=[
                "Record user-visible latency for the primary flow and compare it with the project baseline."
            ],
            approval_points=[
                VerificationApprovalPoint(
                    approval_id=f"approval_{us_id}_release_evidence",
                    title="Review release-critical evidence",
                    required_role="qa_lead",
                    condition="P0 checks have evidence and no unresolved critical failure remains.",
                )
            ],
        ).model_dump(mode="json")

    if stage == "cases":
        return QualityCaseOutput(
            cases=[
                QualityTestCase(
                    case_id=f"case_{us_id}_{index + 1}",
                    scenario_id=f"scenario_{us_id}_{index + 1}",
                    title=title,
                    preconditions=["Required test environment and data are available."],
                    steps=[
                        QualityCaseStep(
                            action="Execute the scenario using the linked system-image context.",
                            expected_result="The expected business outcome is observed and recorded.",
                        )
                    ],
                    expected_results=["The scenario completes with traceable evidence."],
                    test_data_hint="Use representative and boundary data derived from the US.",
                    assertion_type=assertion_type,  # type: ignore[arg-type]
                    priority=priority,  # type: ignore[arg-type]
                    regression_tags=["generated", "requires-review"],
                )
                for index, (title, assertion_type, priority) in enumerate(
                    [
                        ("Primary user journey", "integration", "P0"),
                        ("Supported business branch", "api", "P1"),
                        ("Invalid operation handling", "api", "P0"),
                        ("Permission enforcement", "security", "P0"),
                        ("Related regression path", "integration", "P1"),
                        ("Boundary data handling", "data", "P1"),
                        ("Operational evidence", "event", "P2"),
                    ]
                )
            ]
        ).model_dump(mode="json")

    if stage == "automation":
        return AutomationBlueprintOutput(
            default_base_url=str((tool_input or {}).get("base_url") or "").strip() or None,
            scripts=[
                AutomationScript(
                    script_id=f"automation_{us_id}_primary",
                    title="Primary generated browser validation",
                    linked_case_ids=[f"case_{us_id}_1"],
                    steps=[
                        AutomationStep(action="goto", path="/"),
                        AutomationStep(action="assert_visible", selector="body"),
                    ],
                )
            ],
            selector_strategy=(
                "Prefer data-testid, accessible role, label, and stable business anchors. "
                "Review generated selectors against the target environment before execution."
            ),
            fixture_hints=["Provide a deterministic account and representative US-specific test data."],
        ).model_dump(mode="json")

    return QualityChangeDocumentOutput(
        document_id=f"change_document_{us_id}",
        title=f"Quality change record for {us_id}",
        executive_summary=(
            "Consolidates the requirement, code, system-image, and quality-asset evidence "
            "used to verify this change."
        ),
        deltas=[
            QualityChangeDelta(
                delta_id=f"delta_{us_id}_requirement",
                source_type="requirement",
                summary="The active US defines the intended business behavior and acceptance boundary.",
                object_refs=[f"us:{us_id}"],
                evidence_refs=[f"us:{us_id}"],
            ),
            QualityChangeDelta(
                delta_id=f"delta_{us_id}_quality",
                source_type="test_asset",
                summary="Scope, scenario, plan, case, and automation assets describe the verification delta.",
                object_refs=[
                    "scope_pack:current",
                    "scenario_set:current",
                    "verification_plan:current",
                    "case_set:current",
                    "automation_asset:current",
                ],
                evidence_refs=["quality_asset_pack:current"],
            ),
        ],
        scope_summary="Current scope records impacted behavior, exclusions, regression targets, and risk targets.",
        scenario_summary="Risk-based scenarios cover primary, branch, failure, permission, boundary, and observability paths.",
        case_summary="Structured cases provide executable actions, expected results, data hints, and traceability.",
        risks=[
            QualityChangeRisk(
                risk_id=f"risk_{us_id}_evidence",
                title="Release evidence completeness",
                severity="high",
                rationale="Release confidence depends on current execution evidence and unresolved failures.",
                verification_refs=["verification_plan:current", "run:latest"],
            )
        ],
        evidence_refs=[f"us:{us_id}", "quality_asset_pack:current"],
    ).model_dump(mode="json")


def generation_title(stage: QualityGenerationStage) -> str:
    return {
        "scope": "Test scope pack",
        "scenarios": "Scenario coverage pack",
        "verification_plan": "Verification plan",
        "cases": "Structured test case pack",
        "automation": "Playwright automation blueprint",
        "change_document": "Quality change document",
    }[stage]


def generation_summary(stage: QualityGenerationStage, payload: Dict[str, Any]) -> str:
    if stage == "scope":
        count = sum(len(payload.get(key, [])) for key in ("in_scope", "regression_targets", "risk_targets"))
        return f"Generated {count} traceable scope and risk targets."
    if stage == "scenarios":
        return f"Generated {len(payload.get('scenarios', []))} risk-based test scenarios."
    if stage == "verification_plan":
        return (
            f"Generated {len(payload.get('priorities', []))} verification priorities and "
            f"{len(payload.get('execution_allocations', []))} execution allocations."
        )
    if stage == "cases":
        return f"Generated {len(payload.get('cases', []))} structured test cases."
    if stage == "automation":
        return f"Generated {len(payload.get('scripts', []))} reviewable Playwright automation script(s)."
    return (
        f"Generated a traceable change document with {len(payload.get('deltas', []))} source delta(s) "
        f"and {len(payload.get('risks', []))} risk item(s)."
    )


__all__ = [
    "QUALITY_GENERATION_PROMPTS",
    "DeterministicQualityGenerationAdapter",
    "AutomationBlueprintOutput",
    "AutomationScript",
    "AutomationStep",
    "QualityCaseOutput",
    "QualityChangeDocumentOutput",
    "QualityChangeDelta",
    "QualityChangeRisk",
    "QualityGenerationError",
    "QualityGenerationPort",
    "QualityGenerationRequest",
    "QualityGenerationResult",
    "QualityGenerationStage",
    "QualityPromptDefinition",
    "QualityScenarioOutput",
    "QualityScopeOutput",
    "VerificationApprovalPoint",
    "VerificationExecutionAllocation",
    "VerificationPlanOutput",
    "VerificationPriority",
    "fallback_generation_output",
    "generation_summary",
    "generation_title",
    "output_model_for_stage",
    "prompt_for_stage",
    "validate_generation_output",
]
