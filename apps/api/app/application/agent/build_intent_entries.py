"""Normalize saved-plan UI and chat requests into the same fixed-input goal."""
from __future__ import annotations

import re
from typing import Protocol

from .agent_models import ConversationSession
from ...domain.agent.runtime_models import AgentGoalProposal, ClarificationRequest, OrchestratorDecision, ToolPlanStep
from ...domain.agent.plan_policy import AgentPlanPolicyViolation
from ...domain.system_image.build_plan import TargetedBuildIntent
from ...domain.system_image.image_revision import require_frozen_inputs
from ..system_image.build_plans import BuildPlanApplicationService
from .natural_build_entries import REQUEST_REF
from .source_build_wait import WAIT_REF


DIGEST_REF = "build_plan_digest:"
_ENGLISH_ENTRY = r"(?:start|build|execute|continue)\s+(?:system\s+image\s+from\s+)?build_plan:"
_CHINESE_ENTRY = r"(?:使用|启动|执行|继续)\s*(?:构建计划\s*)?build_plan:"
_ENTRY_PREFIX = re.compile(r"(?:" + _ENGLISH_ENTRY + r"|" + _CHINESE_ENTRY + r")", re.I)
_COMMAND = re.compile(
    _ENGLISH_ENTRY + r"([A-Za-z0-9_-]{1,128})"
    r"(?:\s+digest:(sha256:[a-f0-9]{64}))?\s*[.!]?", re.I)
_CHINESE_COMMAND = re.compile(
    _CHINESE_ENTRY + r"([A-Za-z0-9_-]{1,128})"
    r"(?:\s+(?:digest|摘要):(sha256:[a-f0-9]{64}))?\s*[。！]?", re.I)


class AgentBuildIntentEntryPort(Protocol):
    def compile(self, proposal: AgentGoalProposal) -> list[ToolPlanStep] | None: ...
    def plan(self, conversation: ConversationSession, message: str) -> OrchestratorDecision | None: ...
    def preparation_continuation(self, goal, invocation): ...
    def require_preparation_reuse(self, proposal, existing): ...
    def require_saved_preparation_reuse(self, proposal, existing): ...
    def validate_preparation_goal(self, goal): ...
    def source_input_continuation(self, goal): ...


class AgentBuildIntentEntryApplicationService:
    def __init__(self, plans: BuildPlanApplicationService):
        self.plans = plans
        self.preparations = None

    def _read(self, project_id, plan_id, digest=None):
        try:
            saved = self.plans.read(project_id, plan_id)
            intent = saved.proposal.intent
            if (not isinstance(intent, TargetedBuildIntent) or intent.target is None
                    or saved.project_id != project_id or (digest is not None and saved.plan_digest != digest)):
                raise ValueError("A saved entry requires the displayed v3 plan.")
            self.plans.require_target_current(intent.target)
            manifest = self.plans.manifests.get_manifest(project_id, intent.source_manifest_id)
            require_frozen_inputs(manifest)
            if manifest.members != intent.sources or manifest.content_hash != intent.source_manifest_hash:
                raise ValueError("Saved plan inputs differ from their manifest.")
            work = [item for item in saved.proposal.work_items if item.work_item_id == "structure"]
            if (len(work) != 1 or work[0].proposed_tool_id != "system_image.build.structure"
                    or work[0].capability != "immutable_structure_extraction" or work[0].dependency_ids
                    or work[0].max_model_calls != 0 or work[0].max_tool_calls != 1 or work[0].max_attempts != 1
                    or tuple(work[0].source_binding_ids) != intent.scope_binding_ids):
                raise ValueError("Saved plan has no supported structural work item.")
            return saved
        except Exception as exc:
            raise AgentPlanPolicyViolation("saved_build_intent_unavailable",
                "The saved build intent could not be verified; review its original inputs and target.") from exc

    def compile(self, proposal):
        if any(ref.startswith(WAIT_REF) for ref in proposal.target_refs):
            if self.preparations is None:
                raise AgentPlanPolicyViolation("build_preparation_unavailable", "Build preparation is unavailable.")
            return self.preparations.waiting.compile(proposal)
        if any(ref.startswith(REQUEST_REF) for ref in proposal.target_refs):
            if self.preparations is None:
                raise AgentPlanPolicyViolation("build_preparation_unavailable", "Build preparation is unavailable.")
            return self.preparations.compile(proposal)
        plans = [ref.removeprefix("build_plan:") for ref in proposal.target_refs if ref.startswith("build_plan:")]
        digests = [ref.removeprefix(DIGEST_REF) for ref in proposal.target_refs if ref.startswith(DIGEST_REF)]
        if not digests:
            return None
        projects = [ref.removeprefix("project:") for ref in proposal.target_refs if ref.startswith("project:")]
        if (proposal.goal_template != "system_image_build" or len(plans) != 1 or len(digests) != 1
                or len(projects) != 1 or len(proposal.target_refs) != 3
                or not re.fullmatch(r"sha256:[a-f0-9]{64}", digests[0])):
            raise AgentPlanPolicyViolation("saved_build_intent_scope_changed", "A saved entry requires one fixed project, plan and digest.")
        saved = self._read(projects[0], plans[0], digests[0])
        intent = saved.proposal.intent
        fixed = {"project_id": saved.project_id, "plan_id": saved.plan_id, "plan_digest": saved.plan_digest,
                 "target_baseline_id": intent.target.target_baseline_id}
        return [ToolPlanStep("query.system_image.build_plans.read", {"project_id": saved.project_id, "plan_id": saved.plan_id},
                    reason="Read and reauthorize the original saved intent before requesting execution consent."),
                ToolPlanStep("system_image.build.authorize", {**fixed, "budget": {
                    "max_tool_calls": 1, "max_model_calls": 0,
                    "max_active_seconds": min(intent.budget.max_active_seconds, proposal.max_runtime_seconds),
                    "max_cost_microusd": 0}}, reason="Prepare a separate confirmation for deterministic structure only."),
                ToolPlanStep("system_image.build.structure", fixed,
                    reason="Execute the saved structural work without recapturing sources or publishing the image.")]

    def plan(self, conversation, message):
        # Only an explicit whole-message request is executable. A quoted command
        # in a document, explanation or question is not user execution consent.
        match = _COMMAND.fullmatch(message.strip()) or _CHINESE_COMMAND.fullmatch(message.strip())
        if match is None:
            if _ENTRY_PREFIX.match(message.strip()):
                return self._clarify("The saved-plan command is malformed. Use one build_plan ID and an optional exact SHA-256 digest; no other instructions will be executed.")
            if self.preparations is not None:
                return self.preparations.plan(conversation, message)
            return None
        if conversation.space_type not in {"project", "knowledge"} or not conversation.project_id:
            return self._clarify("Open the project that owns this saved build plan first.")
        try:
            saved = self._read(conversation.project_id, match[1], match[2])
        except AgentPlanPolicyViolation:
            return self._clarify("I could not verify that saved plan in this project. Review its source access, digest and original target; I will not use a different plan.")
        return OrchestratorDecision(kind="agent_goal", agent_goal=AgentGoalProposal(
            goal_template="system_image_build", title="Build from saved system image intent",
            summary="Build the fixed structural candidate, then review its evidence and remaining gaps.",
            goal_description="Use the original saved intent; execution budget, investigation and publication remain separate gates.",
            target_refs=[f"project:{saved.project_id}", f"build_plan:{saved.plan_id}", f"{DIGEST_REF}{saved.plan_digest}"],
            query_keys=[["system-image", saved.project_id], ["system-image-build-plans", saved.project_id]],
            estimated_steps=8, max_runtime_seconds=min(saved.proposal.intent.budget.max_active_seconds, 1800),
            kickoff_message="I will use the saved plan and its original sources and target. Confirm the structural budget separately; this does not approve model calls, test execution or publication."))

    def preparation_continuation(self, goal, invocation):
        if self.preparations is None:
            raise AgentPlanPolicyViolation("build_preparation_unavailable", "Build preparation is unavailable.")
        return self.preparations.continuation(goal, invocation)

    def source_input_continuation(self, goal):
        if self.preparations is None:
            raise AgentPlanPolicyViolation("build_preparation_unavailable", "Build preparation is unavailable.")
        return self.preparations.source_input_continuation(goal)

    def require_preparation_reuse(self, proposal, existing):
        if self.preparations is None:
            raise AgentPlanPolicyViolation("build_preparation_unavailable", "Build preparation is unavailable.")
        self.preparations.require_reuse(proposal, existing)

    def require_saved_preparation_reuse(self, proposal, existing):
        if self.preparations is None:
            raise AgentPlanPolicyViolation("build_preparation_unavailable", "Build preparation is unavailable.")
        self.preparations.require_saved_reuse(proposal, existing)

    def validate_preparation_goal(self, goal):
        if self.preparations is None:
            raise AgentPlanPolicyViolation("build_preparation_unavailable", "Build preparation is unavailable.")
        self.preparations.validate_goal(goal)

    @staticmethod
    def _clarify(question):
        return OrchestratorDecision(kind="clarification", clarification=ClarificationRequest(
            question=question, reason="saved_build_intent", missing_context=["verified_saved_build_intent"]))
