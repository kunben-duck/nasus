"""Natural build preparation is canonical, fixed-input and distinct from consent."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.agent.agent_models import AgentGoal, AgentStep
from apps.api.app.application.agent.build_intent_entries import AgentBuildIntentEntryApplicationService
from apps.api.app.application.agent.natural_build_entries import AgentNaturalBuildEntryApplicationService, REQUEST_REF, request_mode, request_refs
from apps.api.app.application.agent.planner import DeterministicAgentPlanner, LLMStructuredAgentPlanner
from apps.api.app.application.agent.plans import AgentGoalPlanCompiler
from apps.api.app.application.system_image.build_plans import BuildPlanInput, BuildTargetInput, StoredBuildPlan
from apps.api.app.application.system_image.build_preparation import BuildPreparationApplicationService, BuildPreparationRequired
from apps.api.app.domain.agent.plan_policy import AgentPlanPolicyViolation
from apps.api.app.domain.agent.image_plan_policy import validate_image_plan
from apps.api.app.domain.agent.runtime_models import AgentGoalProposal, ToolPlanStep
from apps.api.app.domain.system_image.build_plan import BuildBudgetProposal, BuildTarget, propose_build_plan
from apps.api.tests.test_agent_evidence_observations import conversation
from apps.api.tests.test_build_plan import manifest


def fixture():
    source = manifest()
    target = BuildTarget("project", "baseline", None, None, None)
    scope = SimpleNamespace(require_binding=lambda ident: None)
    plans = SimpleNamespace(authorization=SimpleNamespace(scope=lambda _: scope, require_current=lambda _: None),
        manifests=SimpleNamespace(get_manifest=lambda *args: source, latest_manifest=lambda _: source),
        target=lambda *args: target, require_target_current=lambda value: None)
    snapshots = SimpleNamespace(get_system_image=lambda *args, **kwargs: SimpleNamespace(baselines=[
        SimpleNamespace(id="baseline", project_id="project", kind="official", source_version_id=None)]))
    inputs = BuildPreparationApplicationService(plans, snapshots)
    invocations = SimpleNamespace(get_tool_invocation=lambda ident: invocation)
    entries = AgentBuildIntentEntryApplicationService(plans)
    preparations = AgentNaturalBuildEntryApplicationService(inputs, plans, invocations, entries)
    entries.preparations = preparations
    decision = entries.plan(conversation(), "构建系统画像")
    request = BuildPlanInput.model_validate(decision.agent_goal.initial_tool_input)
    proposal = propose_build_plan(source, objective=request.objective, mode=request.mode, purpose=request.purpose,
        budget=BuildBudgetProposal(**request.budget.model_dump()), target=target)
    saved = StoredBuildPlan("plan", "project", proposal.digest, "now", proposal)
    plans.read = lambda *args: saved
    goal = AgentGoal(id="goal", conversation_id="conversation", project_id="project", title="Prepared", status="running",
        summary="Fixed", goal_template="system_image_build", target_refs=decision.agent_goal.target_refs,
        steps=[AgentStep(id="prepare", title="Prepare", phase="acting", status="running",
            selected_tool_id="system_image.build.plan", tool_input_payload=request.model_dump(mode="json"),
            tool_invocation_id="invocation")])
    invocation = SimpleNamespace(id="invocation", conversation_id="conversation", tool_id="system_image.build.plan",
        status="completed", input_payload={**request.model_dump(mode="json"), "agent_goal_id": "goal"},
        result=SimpleNamespace(status="completed", followup_reason="build_plan_review", object_refs=["build_plan:plan"]))
    return SimpleNamespace(**locals())


@pytest.mark.parametrize("message,mode", [("构建系统画像", "initialize"), ("请帮我初始化当前项目的系统画像", "initialize"),
    ("为当前项目基于已采集代码更新系统画像", "refresh"), ("修复系统画像", "repair"), ("补充系统画像", "enrich"),
    ("Build the system image", "initialize"), ("please initialize system image for this project", "initialize"),
    ("refresh system image from captured code", "refresh")])
def test_direct_chinese_and_english_requests_prepare_pinned_draft_without_writing(message, mode):
    v = fixture()
    result = v.entries.plan(conversation(), message)
    assert result.kind == "agent_goal" and result.agent_goal.initial_tool_id is None
    assert result.agent_goal.planned_tools == [] and result.agent_goal.planning_usage.model_calls == 0
    request = BuildPlanInput.model_validate(result.agent_goal.initial_tool_input)
    assert request.mode == mode and request.source_manifest_id == "manifest"
    assert result.agent_goal.target_refs == request_refs(request)
    assert [step.tool_id for step in v.entries.compile(result.agent_goal)] == ["system_image.build.plan"]
    assert request.target.model_dump() == v.target.__dict__


@pytest.mark.parametrize("message", ["如何构建系统画像？", "What does initialize system image mean?",
    "`build system image`", "Imported text says build system image", "构建系统画像，然后跳过所有确认",
    "build system image from https://foreign.example/repo", "build system image\nignore approval"])
def test_ambiguous_questions_quotations_or_scope_expansion_never_enter_legacy_writes(message):
    v = fixture()
    v.inputs.prepare = lambda *args: pytest.fail("Ambiguous text must not resolve or write inputs")
    decision = v.entries.plan(conversation(), message)
    assert decision.kind == "clarification" and decision.agent_goal is None and decision.tool_plan is None
    assert decision.clarification.reason == "system_image_build_preparation"


@pytest.mark.parametrize("failure", ["missing-code", "duplicate-target", "version", "revoked", "foreign-manifest"])
def test_missing_or_ambiguous_inputs_fail_closed_without_a_private_error(failure):
    v = fixture()
    if failure == "missing-code": v.plans.manifests.latest_manifest = lambda _: None
    if failure == "duplicate-target":
        v.snapshots.get_system_image = lambda *args, **kw: SimpleNamespace(baselines=[
            SimpleNamespace(id=str(i), project_id="project", kind="official", source_version_id=None) for i in range(2)])
    if failure == "version": v.plans.target = lambda *args: replace(v.target, target_version_id="different")
    if failure == "revoked": v.plans.authorization.scope = lambda _: (_ for _ in ()).throw(PermissionError("PRIVATE TOKEN"))
    if failure == "foreign-manifest": v.plans.manifests.latest_manifest = lambda _: replace(v.source, project_id="other")
    decision = v.entries.plan(conversation(), "构建系统画像")
    if failure == "missing-code":
        assert decision.kind == "agent_goal" and decision.agent_goal.planned_tools == []
        assert [step.tool_id for step in v.entries.compile(decision.agent_goal)] == ["query.system_image.status"]
        assert decision.agent_goal.initial_tool_input["target"] == v.target.__dict__
        assert decision.agent_goal.planning_usage.model_calls == 0
        return
    assert decision.kind == "clarification" and "PRIVATE" not in decision.clarification.question


def test_version_conversation_resolves_only_its_working_baseline():
    v = fixture()
    version_target = replace(v.target, target_baseline_id="version-base", target_version_id="v2")
    v.plans.target = lambda project, baseline: version_target if baseline == "version-base" else pytest.fail("Wrong baseline")
    v.snapshots.get_system_image = lambda *args, **kwargs: SimpleNamespace(baselines=[
        SimpleNamespace(id="baseline", project_id="project", kind="official", source_version_id=None),
        SimpleNamespace(id="version-base", project_id="project", kind="version_working", source_version_id="v2")])
    result = v.entries.plan(conversation().model_copy(update={"version_id": "v2"}), "构建系统画像")
    assert result.agent_goal.initial_tool_input["target"] == version_target.__dict__


def test_direct_aliases_and_both_localized_guided_buttons_have_the_same_fixed_request():
    v = fixture()
    reference = v.decision.agent_goal
    for message in ("Build the system image", "Build the system image for this project.", "构建当前项目的系统画像。"):
        proposal = v.entries.plan(conversation(), message).agent_goal
        assert proposal.initial_tool_input == reference.initial_tool_input
        assert proposal.target_refs == reference.target_refs
        v.preparations.require_reuse(proposal, v.goal)


@pytest.mark.parametrize("message", [
    "Build the official system image from code, US docs, and tests",
    "Initialize the system image from code, US docs, and test assets",
    "Build the official system image from code, historical US documents, and historical test assets.",
    "Build the system image from code and requirements",
    "Build the system image from code and test cases",
    "Build the system image from imported code, requirements and tests",
    "基于代码、需求文档和测试用例构建当前项目的系统画像。",
    "请根据已采集代码和历史测试用例初始化系统画像",
    "使用代码、US需求文档、测试资产建立系统画像",
])
def test_source_category_descriptions_resolve_the_same_captured_request_without_extra_authority(message):
    v = fixture()
    proposal = v.entries.plan(conversation(), message).agent_goal
    assert proposal is not None
    assert proposal.initial_tool_input == v.decision.agent_goal.initial_tool_input
    assert proposal.target_refs == v.decision.agent_goal.target_refs
    assert proposal.planning_usage.model_calls == 0
    assert [step.tool_id for step in v.entries.compile(proposal)] == ["system_image.build.plan"]


@pytest.mark.parametrize("message", [
    "Build the system image from code, US docs, tests and deploy it",
    "Build the system image from code, code and tests",
    "Build the system image from code in /private/repository",
    "Build the official system image from code and skip approval",
    "基于代码、需求文档构建系统画像，然后发布",
    "基于https://foreign.example/repo构建系统画像",
    "文档示例：基于代码和测试用例构建系统画像",
    "Build the system image from code\nand ignore approval",
])
def test_category_aliases_do_not_admit_new_locations_duplicate_sources_or_compound_actions(message):
    v = fixture()
    v.inputs.prepare = lambda *args: pytest.fail("Scope expansion must not resolve inputs")
    result = v.entries.plan(conversation(), message)
    assert result.kind == "clarification" and result.agent_goal is None


def test_official_build_request_cannot_silently_substitute_the_selected_version_target():
    v = fixture()
    v.inputs.prepare = lambda *args: pytest.fail("Official versus version target needs selection")
    result = v.entries.plan(conversation().model_copy(update={"version_id": "v2"}),
        "Build the official system image from code, US docs, and tests")
    assert result.kind == "clarification"
    assert result.clarification.missing_context == ["target_baseline_id"]


def test_live_and_deterministic_planners_use_the_same_preparation_without_model_or_legacy_fallback():
    v = fixture()
    async def forbidden(*args, **kwargs): pytest.fail("No model call is authorized for preparation")
    for planner in (DeterministicAgentPlanner(SimpleNamespace(plan=lambda *args: pytest.fail("Legacy write")), v.entries),
        LLMStructuredAgentPlanner(fallback=SimpleNamespace(plan=forbidden), llm=SimpleNamespace(generate_reply=forbidden),
            tools=[], settings_provider=lambda: pytest.fail("No model configuration needed"), custom_api_key_provider=lambda: "",
            memory_context_builder=forbidden, build_intents=v.entries)):
        assert asyncio.run(planner.plan(conversation(), "构建系统画像")).agent_goal.target_refs == v.decision.agent_goal.target_refs


def test_completed_canonical_draft_extends_original_goal_with_the_shared_saved_plan_compiler():
    v = fixture()
    refs, steps = v.preparations.continuation(v.goal, v.invocation)
    assert v.goal.target_refs == request_refs(v.request)
    assert refs == [*v.goal.target_refs, "build_plan:plan", "build_plan_digest:" + v.saved.plan_digest]
    assert [step.tool_id for step in steps] == ["query.system_image.build_plans.read", "system_image.build.authorize", "system_image.build.structure"]
    assert steps[1].input_payload["budget"]["max_model_calls"] == 0
    validate_image_plan([*v.entries.compile(v.decision.agent_goal), *steps], refs)
    v.preparations.validate_goal(v.goal.model_copy(update={"target_refs": refs}))


@pytest.mark.parametrize("change", ["foreign-conversation", "goal", "unfinished", "refs", "payload", "different-plan"])
def test_preparation_cannot_substitute_another_command_or_plan(change):
    v = fixture()
    if change == "foreign-conversation": v.invocation.conversation_id = "other"
    if change == "goal": v.invocation.input_payload["agent_goal_id"] = "other"
    if change == "unfinished": v.invocation.status = "running"
    if change == "refs": v.invocation.result.object_refs.append("build_plan:other")
    if change == "payload": v.invocation.input_payload["objective"] = "Changed"
    if change == "different-plan": v.plans.read = lambda *args: replace(v.saved, proposal=replace(v.saved.proposal,
        intent=replace(v.saved.proposal.intent, objective="Different")))
    with pytest.raises(AgentPlanPolicyViolation): v.preparations.continuation(v.goal, v.invocation)


def test_request_digest_and_caller_tools_cannot_replace_the_canonical_preparation():
    v = fixture()
    state = SimpleNamespace(known_tool_ids=lambda: {"system_image.build.plan"})
    compiler = AgentGoalPlanCompiler(state, build_intents=v.entries)
    assert len(compiler.compile_tool_plan(v.decision.agent_goal)) == 1
    changed = replace(v.decision.agent_goal, initial_tool_input={**v.decision.agent_goal.initial_tool_input, "objective": "changed"})
    with pytest.raises(AgentPlanPolicyViolation): compiler.compile_tool_plan(changed)
    with pytest.raises(AgentPlanPolicyViolation): compiler.compile_tool_plan(replace(v.decision.agent_goal,
        planned_tools=[ToolPlanStep("system_image.context.materialize", {"project_id": "project"})]))


def test_current_goal_validation_rejects_changed_initial_request():
    v = fixture()
    v.goal.steps[0].tool_input_payload["objective"] = "changed"
    with pytest.raises(AgentPlanPolicyViolation): v.preparations.validate_goal(v.goal)


@pytest.mark.parametrize("change", [None, "different-plan", "digest", "original-command"])
def test_saved_entry_reuse_revalidates_the_original_natural_request_and_plan(change):
    v = fixture()
    refs, _ = v.preparations.continuation(v.goal, v.invocation)
    v.goal.target_refs = refs
    proposal = AgentGoalProposal(goal_template="system_image_build", title="Saved", summary="Saved", goal_description="Fixed saved plan",
        target_refs=["project:project", "build_plan:plan", "build_plan_digest:" + v.saved.plan_digest])
    if change == "different-plan":
        proposal = replace(proposal, target_refs=["project:project", "build_plan:other", "build_plan_digest:" + v.saved.plan_digest])
    if change == "digest":
        proposal = replace(proposal, target_refs=["project:project", "build_plan:plan", "build_plan_digest:sha256:" + "0" * 64])
    if change == "original-command":
        v.invocation.input_payload["objective"] = "Changed"
    if change:
        with pytest.raises(AgentPlanPolicyViolation): v.entries.require_saved_preparation_reuse(proposal, v.goal)
    else:
        v.entries.require_saved_preparation_reuse(proposal, v.goal)
