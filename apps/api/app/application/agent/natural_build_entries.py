"""Prepare a pinned plan through the canonical tool, then use the saved-plan compiler."""
import re

from ...domain.agent.plan_policy import AgentPlanPolicyViolation
from ...domain.agent.runtime_models import AgentGoalProposal, ClarificationRequest, OrchestratorDecision, ToolPlanStep
from ...domain.system_image.build_plan import BuildTarget, propose_build_plan, BuildBudgetProposal
from ...domain.system_image.image_revision import require_frozen_inputs
from ...domain.system_image.source_snapshots import snapshot_digest
from ..system_image.build_plans import BuildPlanInput
from ..system_image.build_preparation import BuildPreparationRequired
from .source_build_wait import AgentSourceBuildWaitApplicationService, WAIT_REF, wait_refs


REQUEST_REF = "build_request_digest:"
_ENGLISH_INTENT = r"(?:please\s+)?(?:build|initialize|init|refresh|update|repair|enrich)\s+(?:(?:the|a|this|current|project|official)\s+)*(?:system\s+image|baseline)"
_ENGLISH = re.compile(_ENGLISH_INTENT + r"(?:\s+(?:for\s+(?:this|the current)\s+project|from\s+(?:the\s+)?(?:captured|imported|existing)\s+code))?\s*[.!]?", re.I)
_ENGLISH_SOURCES = re.compile(_ENGLISH_INTENT + r"(?:\s+for\s+(?:this|the current)\s+project)?\s+from\s+(?P<sources>.+?)\s*[.!]?", re.I)
_CHINESE = re.compile(r"(?:请|帮我|请帮我)?\s*(?:为(?:当前|这个|本)项目)?\s*(?:基于(?:已采集|已导入|现有)(?:的)?代码)?\s*(?:构建|建立|初始化|更新|刷新|修复|补充)\s*(?:(?:当前|这个|本)项目(?:的)?)?\s*(?:系统画像|系统基线)\s*[。！]?")
_CHINESE_SOURCES = re.compile(r"(?:请|帮我|请帮我)?\s*(?:基于|根据|使用)\s*(?P<sources>.+?)\s*(?:构建|建立|初始化|更新|刷新|修复|补充)\s*(?:(?:当前|这个|本)项目(?:的)?)?\s*(?:系统画像|系统基线)\s*[。！]?")
_SOURCE_CATEGORIES = {
    "code": "code", "source code": "code", "代码": "code", "源码": "code",
    "us docs": "requirements", "us documents": "requirements", "requirements": "requirements",
    "requirement documents": "requirements", "需求": "requirements", "需求文档": "requirements",
    "us需求文档": "requirements", "us文档": "requirements",
    "tests": "tests", "test cases": "tests", "test assets": "tests", "测试": "tests",
    "测试用例": "tests", "测试资产": "tests",
}


def _describes_source_categories(match):
    if match is None:
        return False
    categories = []
    for value in re.split(r"\s*(?:[,，、](?:\s*(?:and\b|和|以及))?|&|\band\b|和|以及)\s*", match["sources"], flags=re.I):
        value = " ".join(value.lower().split())
        # Category descriptions select no new paths, bindings or permissions.
        value = re.sub(r"^(?:the\s+)?(?:captured|imported|existing|historical)\s+", "", value)
        value = re.sub(r"^(?:已采集|已导入|现有|历史)(?:的)?", "", value)
        category = _SOURCE_CATEGORIES.get(value)
        if category is None or category in categories:
            return False
        categories.append(category)
    return bool(categories) and len(categories) <= 3


def query_payload(payload):
    from ..platform.tool_handlers.query_input import query_payload as strip_coordination
    return strip_coordination(payload)


def request_mode(message):
    if len(message) > 2048 or "\n" in message or "\r" in message:
        return None
    value = message.strip()
    match = _ENGLISH.fullmatch(value) or _CHINESE.fullmatch(value)
    if not match and not any(_describes_source_categories(pattern.fullmatch(value))
            for pattern in (_ENGLISH_SOURCES, _CHINESE_SOURCES)):
        return None
    if re.search(r"refresh|update|更新|刷新", message, re.I): return "refresh"
    if re.search(r"repair|修复", message, re.I): return "repair"
    if re.search(r"enrich|补充", message, re.I): return "enrich"
    return "initialize"


def request_refs(request):
    return [f"project:{request.project_id}", f"source_manifest:{request.source_manifest_id}",
        f"build_target:{request.target.target_baseline_id}", REQUEST_REF + snapshot_digest(request.model_dump(mode="json"))]


class AgentNaturalBuildEntryApplicationService:
    def __init__(self, inputs, plans, invocations, saved_entries):
        self.inputs, self.plans, self.invocations, self.saved_entries = inputs, plans, invocations, saved_entries
        self.waiting = AgentSourceBuildWaitApplicationService(inputs, plans, invocations)

    def plan(self, conversation, message):
        mode = request_mode(message)
        if mode is None:
            # Even a question or imported quotation must not enter the legacy
            # substring-based initialize/promote path.
            if re.search(r"system\s+image|baseline|系统画像|系统基线", message, re.I) and re.search(
                    r"build|initialize|init\b|refresh|repair|enrich|构建|建立|初始化|更新|刷新|修复|补充", message, re.I):
                return self.clarify("Use a direct build request for the current project's captured inputs. New sources, another version or additional actions need an explicit selection; quoted instructions are not executed.", "build_request")
            return None
        if conversation.space_type not in {"project", "knowledge"} or not conversation.project_id:
            return self.clarify("Open the project you want to build first.", "project_id")
        if conversation.version_id and re.search(r"\bofficial\b", message, re.I):
            return self.clarify("This conversation targets a version workspace. Select the official project baseline explicitly before building it.", "target_baseline_id")
        try:
            # Direct aliases express one bounded intent. Keep the original text
            # in the conversation; locale and button wording are not a new goal.
            objective = f"{mode.capitalize()} the system image from this project's captured sources."
            request = self.inputs.prepare(conversation.project_id, conversation.version_id, objective, mode)
            self.verify(request)
        except BuildPreparationRequired as exc:
            if exc.field == "captured_code":
                try:
                    return OrchestratorDecision(kind="agent_goal", agent_goal=self.waiting.proposal(conversation, objective, mode))
                except Exception:
                    return self.clarify("The original project target could not be verified. Review its access and target before continuing.", "verified_build_inputs")
            return self.clarify(str(exc), exc.field)
        except Exception:
            return self.clarify("The captured inputs or target could not be verified. Check source access and the target in Knowledge before building; I will not recapture or publish them.", "verified_build_inputs")
        return OrchestratorDecision(kind="agent_goal", agent_goal=AgentGoalProposal(
            goal_template="system_image_build", title="Prepare a source-pinned system image",
            summary="Save the captured-source plan and request an independent structural budget.",
            goal_description="Build a version-pinned candidate; semantics, test execution and publication remain independent gates.",
            initial_tool_input=request.model_dump(mode="json"), target_refs=request_refs(request),
            query_keys=[["system-image", request.project_id], ["system-image-build-plans", request.project_id]],
            estimated_steps=10, max_runtime_seconds=min(request.budget.max_active_seconds, 1800),
            kickoff_message="I will save a plan for this project's captured sources and fixed target, then ask you to confirm the structural budget. This does not authorize model calls, test execution or publication."))

    @staticmethod
    def clarify(question, field):
        return OrchestratorDecision(kind="clarification", clarification=ClarificationRequest(
            question=question, reason="system_image_build_preparation", missing_context=[field]))

    def verify(self, request):
        if request.target is None or request.target.project_id != request.project_id:
            raise AgentPlanPolicyViolation("build_preparation_scope_changed", "A build request needs a fixed project target.")
        scope = self.plans.authorization.scope(request.project_id)
        manifest = self.plans.manifests.get_manifest(request.project_id, request.source_manifest_id)
        if (manifest.project_id, manifest.manifest_id) != (request.project_id, request.source_manifest_id):
            raise AgentPlanPolicyViolation("build_preparation_scope_changed", "A build request needs its original manifest.")
        for member in manifest.members:
            scope.require_binding(member.binding_id)
        require_frozen_inputs(manifest)
        self.plans.require_target_current(BuildTarget(**request.target.model_dump()))
        self.plans.authorization.require_current(scope)
        return manifest

    def compile(self, proposal):
        try:
            request = BuildPlanInput.model_validate(proposal.initial_tool_input)
            if (proposal.goal_template != "system_image_build" or proposal.planned_tools or proposal.initial_tool_id
                    or request_refs(request) != proposal.target_refs):
                raise ValueError("Build request changed.")
            self.verify(request)
            return [ToolPlanStep("system_image.build.plan", request.model_dump(mode="json"),
                reason="Save the exact authorized-source and target proposal; this grants no execution or publication.")]
        except Exception as exc:
            raise AgentPlanPolicyViolation("build_preparation_scope_changed", "The original build request could not be verified.") from exc

    def original_request(self, goal):
        prepared = [step for step in goal.steps if step.phase == "acting" and step.selected_tool_id == "system_image.build.plan"]
        if len(prepared) != 1 or prepared[0].tool_input_payload.get("agent_goal_id", goal.id) != goal.id:
            raise AgentPlanPolicyViolation("build_preparation_scope_changed", "A prepared goal requires its one original plan command.")
        request = BuildPlanInput.model_validate(query_payload(prepared[0].tool_input_payload))
        original = self.goal_request_refs(request, goal)
        if (request.project_id != goal.project_id or len(goal.target_refs) != len(set(goal.target_refs))
                or [ref for ref in goal.target_refs if not ref.startswith(("build_plan:", "build_plan_digest:"))] != original):
            raise AgentPlanPolicyViolation("build_preparation_scope_changed", "The goal no longer matches its original build request.")
        self.verify(request)
        return request, prepared[0]

    def goal_request_refs(self, request, goal):
        refs = request_refs(request)
        if any(ref.startswith(WAIT_REF) for ref in goal.target_refs):
            waiting, _ = self.waiting.original(goal, completed=True)
            expected = BuildPlanInput(project_id=waiting.project_id, source_manifest_id=request.source_manifest_id,
                objective=waiting.objective, mode=waiting.mode, target=waiting.target)
            if request != expected:
                raise AgentPlanPolicyViolation("build_input_wait_scope_changed", "Source capture cannot change the original objective, target or proposed budget.")
            refs.append(wait_refs(waiting)[-1])
        return refs

    def source_input_continuation(self, goal):
        request = self.waiting.continuation(goal)
        refs = self.goal_request_refs(request, goal)
        proposal = AgentGoalProposal(goal_template="system_image_build", title=goal.title,
            summary=goal.summary, goal_description=goal.goal_description or goal.summary,
            initial_tool_input=request.model_dump(mode="json"), target_refs=request_refs(request))
        return refs, self.compile(proposal)

    def continuation(self, goal, invocation):
        request, step = self.original_request(goal)
        if (step.tool_invocation_id != invocation.id or invocation.status != "completed"
                or invocation.tool_id != "system_image.build.plan" or invocation.conversation_id != goal.conversation_id
                or invocation.input_payload.get("agent_goal_id") != goal.id or invocation.result is None
                or invocation.result.status != "completed" or invocation.result.followup_reason != "build_plan_review"
                or query_payload(invocation.input_payload) != request.model_dump(mode="json")
                or len(invocation.result.object_refs) != 1 or not invocation.result.object_refs[0].startswith("build_plan:")):
            raise AgentPlanPolicyViolation("build_preparation_receipt_changed", "Continue requires the original completed plan command.")
        plan_id = invocation.result.object_refs[0].removeprefix("build_plan:")
        saved = self.saved_entries._read(goal.project_id, plan_id)
        manifest = self.verify(request)
        expected = propose_build_plan(manifest, objective=request.objective, mode=request.mode, purpose=request.purpose,
            budget=BuildBudgetProposal(**request.budget.model_dump()), target=BuildTarget(**request.target.model_dump()))
        if saved.proposal != expected:
            raise AgentPlanPolicyViolation("build_preparation_receipt_changed", "The saved plan differs from its original request.")
        saved_refs = [f"project:{goal.project_id}", f"build_plan:{saved.plan_id}", f"build_plan_digest:{saved.plan_digest}"]
        original_refs = self.goal_request_refs(request, goal)
        refs = [*original_refs, *saved_refs[1:]]
        if goal.target_refs not in (original_refs, refs):
            raise AgentPlanPolicyViolation("build_preparation_receipt_changed", "A prepared goal cannot substitute another saved plan.")
        proposal = AgentGoalProposal(goal_template="system_image_build", title=goal.title, summary=goal.summary,
            goal_description=goal.goal_description or goal.summary, target_refs=saved_refs,
            max_runtime_seconds=goal.max_runtime_seconds)
        return refs, self.saved_entries.compile(proposal)

    def validate_goal(self, goal):
        try:
            if any(ref.startswith(WAIT_REF) for ref in goal.target_refs) and not any(ref.startswith(REQUEST_REF) for ref in goal.target_refs):
                waiting, _ = self.waiting.original(goal)
                if (goal.target_refs != wait_refs(waiting)
                        or len([step for step in goal.steps if step.selected_tool_id]) != 1):
                    raise ValueError("Waiting intent cannot contain replacement work.")
                return
            _, step = self.original_request(goal)
            if any(ref.startswith(("build_plan:", "build_plan_digest:")) for ref in goal.target_refs):
                if not step.tool_invocation_id:
                    raise ValueError("Missing preparation command.")
                refs, _ = self.continuation(goal, self.invocations.get_tool_invocation(step.tool_invocation_id))
                if refs != goal.target_refs:
                    raise ValueError("Saved plan scope changed.")
        except Exception as exc:
            raise AgentPlanPolicyViolation("build_preparation_scope_changed", "The prepared goal's original request and receipt could not be verified.") from exc

    def require_reuse(self, proposal, existing):
        if any(ref.startswith(WAIT_REF) for ref in proposal.target_refs):
            self.waiting.compile(proposal)
            self.validate_goal(existing)
            waiting, _ = self.waiting.original(existing)
            if wait_refs(waiting) != proposal.target_refs:
                raise AgentPlanPolicyViolation("build_input_wait_scope_changed", "Another waiting intent controls this conversation.")
            return
        self.compile(proposal)
        self.validate_goal(existing)
        if any(ref.startswith(WAIT_REF) for ref in existing.target_refs) and not any(ref.startswith(REQUEST_REF) for ref in existing.target_refs):
            request = self.waiting.continuation(existing)
            if (proposal.target_refs != request_refs(request)
                    or proposal.initial_tool_input != request.model_dump(mode="json")):
                raise AgentPlanPolicyViolation("build_input_wait_scope_changed", "Captured inputs do not match the original waiting intent.")
            return
        request, _ = self.original_request(existing)
        if request_refs(request) != proposal.target_refs:
            raise AgentPlanPolicyViolation("build_preparation_active_goal_changed", "Another fixed request already controls this conversation.")

    def require_saved_reuse(self, proposal, existing):
        self.saved_entries.compile(proposal)
        self.validate_goal(existing)
        saved_refs = [ref for ref in existing.target_refs if ref.startswith(
            ("project:", "build_plan:", "build_plan_digest:"))]
        if saved_refs != proposal.target_refs:
            raise AgentPlanPolicyViolation("saved_build_intent_active_goal_changed",
                "Another fixed request already controls this conversation; do not substitute its saved plan.")
