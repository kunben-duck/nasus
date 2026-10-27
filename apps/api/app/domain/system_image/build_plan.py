from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional, Union

from .source_snapshots import CapturedSourceManifest, SourceManifestMember, snapshot_digest


PLAN_POLICY = "nasus.image-investigation-plan.v2"
LEGACY_PLAN_POLICY = "nasus.image-investigation-plan.v1"
TARGETED_PLAN_POLICY = "nasus.image-investigation-plan.v3"
MAX_PLAN_BYTES = 64 * 1024


class BuildPlanIntegrityError(RuntimeError):
    pass


def _text(value, maximum=2000):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


def _texts(values, maximum=80):
    return isinstance(values, tuple) and 0 < len(values) <= maximum and all(_text(value) for value in values)


@dataclass(frozen=True)
class BuildBudgetProposal:
    max_tool_calls: int = 80
    max_model_calls: int = 30
    max_active_seconds: int = 1200
    max_cost_microusd: Optional[int] = None

    def __post_init__(self):
        for name, maximum in (("max_tool_calls", 1000), ("max_model_calls", 1000), ("max_active_seconds", 86400)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("Invalid proposed build budget.")
        if self.max_cost_microusd is not None and (type(self.max_cost_microusd) is not int or not 0 <= self.max_cost_microusd <= 10**9):
            raise ValueError("Invalid proposed cost ceiling.")


@dataclass(frozen=True)
class BuildIntent:
    project_id: str
    objective: str
    mode: str
    purpose: str
    source_manifest_id: str
    source_manifest_hash: str
    sources: tuple[SourceManifestMember, ...]
    budget: BuildBudgetProposal
    autonomy_policy: str = "guided"
    expected_head: Optional[str] = None
    expected_head_status: str = "unresolved"

    def __post_init__(self):
        if (not _text(self.project_id, 128) or not _text(self.source_manifest_id, 128) or not _text(self.objective)
                or self.mode not in {"initialize", "enrich", "refresh", "repair"}
                or self.purpose not in {"structure", "behavior", "traceability"}
                or self.autonomy_policy != "guided" or self.expected_head is not None or self.expected_head_status != "unresolved"):
            raise ValueError("Invalid build intent or unsupported authorization claim.")
        if (not self.sources or len(self.sources) > 64 or len({item.binding_id for item in self.sources}) != len(self.sources)
                or tuple(sorted(self.sources, key=lambda item: item.binding_id)) != self.sources
                or snapshot_digest([asdict(item) for item in self.sources]) != self.source_manifest_hash):
            raise BuildPlanIntegrityError("Build sources do not match the fixed manifest.")
        for item in self.sources:
            if (not _text(item.binding_id, 128) or item.source_type not in {"code", "us_doc", "test_asset"}
                    or item.status not in {"captured", "failed", "pending", "legacy_unverified"}
                    or (item.status == "captured" and not _text(item.source_revision_id, 128))
                    or (item.status != "captured" and item.source_revision_id is not None)):
                raise BuildPlanIntegrityError("Invalid source capture in build intent.")


@dataclass(frozen=True)
class BuildTarget:
    project_id: str
    target_baseline_id: str
    target_version_id: Optional[str]
    expected_head_id: Optional[str]
    expected_head_hash: Optional[str]

    def __post_init__(self):
        def identifier(value):
            return _text(value, 128) and not any(ord(char) < 32 for char in value)
        if (not identifier(self.project_id) or not identifier(self.target_baseline_id)
                or (self.target_version_id is not None and not identifier(self.target_version_id))
                or (self.expected_head_id is None) != (self.expected_head_hash is None)
                or (self.expected_head_id is not None and not identifier(self.expected_head_id))):
            raise BuildPlanIntegrityError("Invalid fixed build target.")
        if self.expected_head_hash is not None:
            value = self.expected_head_hash
            if (type(value) is not str or len(value) != 71 or not value.startswith("sha256:")
                    or any(char not in "0123456789abcdef" for char in value[7:])):
                raise BuildPlanIntegrityError("Invalid expected publication image hash.")


@dataclass(frozen=True)
class TargetedBuildIntent(BuildIntent):
    target: Optional[BuildTarget] = None
    scope_binding_ids: tuple[str, ...] = ()

    def __post_init__(self):
        # Keep legacy intent serialization unchanged, including old plan digests.
        BuildIntent(self.project_id, self.objective, self.mode, self.purpose, self.source_manifest_id,
            self.source_manifest_hash, self.sources, self.budget, self.autonomy_policy)
        if (not isinstance(self.target, BuildTarget) or self.target.project_id != self.project_id
                or self.scope_binding_ids != tuple(item.binding_id for item in self.sources)
                or self.expected_head_status != "resolved" or self.expected_head != self.target.expected_head_id):
            raise BuildPlanIntegrityError("Build intent target, head or source scope mismatch.")


@dataclass(frozen=True)
class InvestigationWorkItem:
    work_item_id: str
    question: str
    reason: str
    capability: str
    proposed_tool_id: Optional[str]
    binding_state: str
    source_binding_ids: tuple[str, ...]
    dependency_ids: tuple[str, ...]
    output_artifact: str
    acceptance_conditions: tuple[str, ...]
    max_attempts: int
    max_tool_calls: int
    max_model_calls: int
    failure_action: str


@dataclass(frozen=True)
class BuildPlanGap:
    code: str
    blocks: str
    reason: str
    required_action: str


@dataclass(frozen=True)
class InvestigationPlan:
    intent: Union[TargetedBuildIntent, BuildIntent]
    work_items: tuple[InvestigationWorkItem, ...]
    gaps: tuple[BuildPlanGap, ...]
    completion_conditions: tuple[str, ...]
    policy_version: str = PLAN_POLICY
    state: str = "draft"
    authorization_state: str = "not_granted"
    execution_ready: bool = False

    def __post_init__(self):
        if (self.policy_version not in {PLAN_POLICY, LEGACY_PLAN_POLICY, TARGETED_PLAN_POLICY}
                or (self.policy_version == TARGETED_PLAN_POLICY) != isinstance(self.intent, TargetedBuildIntent)
                or self.state != "draft" or self.authorization_state != "not_granted" or self.execution_ready is not False):
            raise ValueError("A plan draft cannot authorize execution or publication.")
        if not 1 <= len(self.work_items) <= 80 or not _texts(self.completion_conditions) or len(self.gaps) > 80:
            raise ValueError("Investigation plan requires bounded work and completion criteria.")
        for gap in self.gaps:
            if not all(_text(value) for value in (gap.code, gap.blocks, gap.reason, gap.required_action)):
                raise ValueError("Investigation gaps require explicit reasons and next actions.")
        seen = set()
        allowed = {item.binding_id for item in self.intent.sources}
        for item in self.work_items:
            if (not _text(item.work_item_id, 128) or item.work_item_id in seen or not set(item.dependency_ids).issubset(seen)
                    or len(set(item.dependency_ids)) != len(item.dependency_ids)
                    or not _texts(item.source_binding_ids, 64) or not set(item.source_binding_ids).issubset(allowed)
                    or len(set(item.source_binding_ids)) != len(item.source_binding_ids)
                    or item.binding_state not in {"requires_pinned_executor", "requires_confirmation", "requires_capability", "requires_artifact"}
                    or item.proposed_tool_id not in {None, "system_image.context.materialize", "system_image.build.structure", "query.system_image.revisions.read"}
                    or not all(_text(value) for value in (item.question, item.reason, item.capability, item.output_artifact))
                    or not _texts(item.acceptance_conditions)
                    or type(item.max_attempts) is not int or item.max_attempts != 1
                    or type(item.max_tool_calls) is not int or not 1 <= item.max_tool_calls <= 80
                    or type(item.max_model_calls) is not int or not 0 <= item.max_model_calls <= 30
                    or item.failure_action not in {"pause_for_input", "record_gap", "pause_for_review"}):
                raise ValueError("Invalid investigation DAG, scope, tool binding or budget.")
            seen.add(item.work_item_id)
        if (sum(item.max_tool_calls for item in self.work_items) > self.intent.budget.max_tool_calls
                or sum(item.max_model_calls for item in self.work_items) > self.intent.budget.max_model_calls):
            raise ValueError("Proposed work exceeds the requested budget.")

    @property
    def digest(self):
        return snapshot_digest(asdict(self))


def propose_build_plan(manifest: CapturedSourceManifest, *, objective: str, mode: str, purpose: str,
                       budget: BuildBudgetProposal, target: Optional[BuildTarget] = None) -> InvestigationPlan:
    sources = tuple(sorted(manifest.members, key=lambda item: item.binding_id))
    intent = BuildIntent(manifest.project_id, objective.strip(), mode, purpose, manifest.manifest_id,
                         manifest.content_hash, sources, budget)
    if target is not None:
        intent = TargetedBuildIntent(manifest.project_id, objective.strip(), mode, purpose, manifest.manifest_id,
            manifest.content_hash, sources, budget, expected_head=target.expected_head_id,
            expected_head_status="resolved", target=target, scope_binding_ids=tuple(item.binding_id for item in sources))
    bindings = tuple(item.binding_id for item in sources)
    code = tuple(item for item in sources if item.source_type == "code")
    gaps = [
        BuildPlanGap("execution_authorization_required", "execution", "A proposal is not a scope or budget grant.", "Review the exact plan digest and issue an execution envelope."),
        BuildPlanGap("structural_confirmation_required", "structural_execution", "The pinned structural executor requires a confirmed plan digest and explicit candidate target.", "Confirm one structural task with system_image.build.structure; this does not authorize the whole plan."),
        BuildPlanGap("revision_governance_required", "publication", "An official image head and publication approval have not been resolved.", "Resolve the target and expected head under revision governance."),
    ]
    if not code or any(item.status != "captured" for item in code):
        gaps.append(BuildPlanGap("captured_code_required", "structure", "Every selected required code source needs an immutable capture.", "Capture or repair the required code sources, then propose a new plan."))
    for kind, capability in (("us_doc", "business_acceptance"), ("test_asset", "test_reuse")):
        optional = [item for item in sources if item.source_type == kind]
        if not optional or any(item.status != "captured" for item in optional):
            gaps.append(BuildPlanGap(f"{kind}_unavailable", capability, "Optional enrichment is absent or not captured; structural work may continue.", "Add or repair this source before relying on its enrichment."))
    work = [InvestigationWorkItem(
        "structure", "Which code structures and entry points are supported by the selected inputs?",
        "Establish a source-pinned structural candidate without treating inferred rules as approved facts.",
        "immutable_structure_extraction", "system_image.build.structure", "requires_confirmation", bindings, (),
        "image_candidate", ("required code captured", "inventory complete or exclusions explicit", "object and evidence membership verified"),
        1, 1, 0, "pause_for_input"),
        InvestigationWorkItem("review", "Which requested conclusions still lack evidence?",
        "Candidate counts do not establish semantic coverage or business acceptance.", "candidate_evidence_review",
        "query.system_image.revisions.read", "requires_artifact", bindings, ("structure",),
        "build_completion_report", ("candidate digest fixed", "readiness dimensions justified", "remaining gaps and next actions recorded"),
        1, 1, 0, "pause_for_review")]
    if purpose != "structure":
        work.insert(1, InvestigationWorkItem("semantics", "How do observed behavior, requirements and tests support or conflict with one another?",
            "Missing expected rules must remain unknown, not be invented from code.", "typed_semantic_investigation", None,
            "requires_capability", bindings, ("structure",), "proposed_behavior_and_links",
            ("field-level source evidence", "observed and expected claims separated", "conflicts retained"), 1, 1, 1, "record_gap"))
        gaps.append(BuildPlanGap("semantic_investigation_required", purpose, "Typed semantic investigation and model egress authorization are not bound.", "Bind the semantic capability and authorized model route before executing this work."))
        if budget.max_cost_microusd is None:
            gaps.append(BuildPlanGap("cost_ceiling_required", "semantic_execution", "No model cost ceiling has been proposed.", "Request a bounded cost ceiling for administrator approval."))
        review = work.pop()
        work.append(InvestigationWorkItem(**{**asdict(review), "dependency_ids": ("structure", "semantics")}))
    if target is not None:
        gaps = [gap for gap in gaps if gap.code != "revision_governance_required"]
        gaps.append(BuildPlanGap("publication_approval_required", "publication",
            "The target head is fixed, but building does not approve publication.",
            "Review the candidate against this expected head under independent publication governance."))
    return InvestigationPlan(intent, tuple(work), tuple(gaps), (
        "All required artifacts verified against the fixed inputs.",
        "Structure, behavior, traceability, automation and execution readiness reported separately.",
        "Candidate delivery distinguished from approved publication.",
    ), policy_version=TARGETED_PLAN_POLICY if target is not None else PLAN_POLICY)


def decode_build_plan(payload: dict) -> InvestigationPlan:
    try:
        intent = payload["intent"]
        intent_values = {**intent, "sources": tuple(SourceManifestMember(**item) for item in intent["sources"]),
            "budget": BuildBudgetProposal(**intent["budget"])}
        intent_class = BuildIntent
        if payload["policy_version"] == TARGETED_PLAN_POLICY:
            intent_class = TargetedBuildIntent
            intent_values.update(target=BuildTarget(**intent["target"]), scope_binding_ids=tuple(intent["scope_binding_ids"]))
        result = InvestigationPlan(
            intent=intent_class(**intent_values),
            work_items=tuple(InvestigationWorkItem(**{**item, **{key: tuple(item[key]) for key in (
                "source_binding_ids", "dependency_ids", "acceptance_conditions")}}) for item in payload["work_items"]),
            gaps=tuple(BuildPlanGap(**item) for item in payload["gaps"]),
            **{key: payload[key] for key in ("policy_version", "state", "authorization_state", "execution_ready")},
            completion_conditions=tuple(payload["completion_conditions"]),
        )
        if snapshot_digest(payload) != result.digest:
            raise BuildPlanIntegrityError("Noncanonical plan payload.")
        return result
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise BuildPlanIntegrityError("Invalid persisted investigation plan.") from exc
