import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from apps.api.app.application.agent.agent_models import AgentGoal
from apps.api.app.application.agent.graph import LocalAgentGraphRuntime
from apps.api.app.application.agent.plans import AgentGoalPlanCompiler
from apps.api.app.application.agent.planner import LLMStructuredAgentPlanner
from apps.api.app.application.agent.replanning import AgentReplanDecision, AgentReplanRequest
from apps.api.app.application.platform.tool_evidence import ToolEvidenceObservationApplicationService
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.platform.tool_plans import ToolBuildPlanObservationApplicationService
from apps.api.app.application.system_image.build_plans import StoredBuildPlan
from apps.api.app.application.system_image.build_plan_queries import BuildPlanReadInput, BuildPlanQueryApplicationService, READ_BUILD_PLAN_TOOL
from apps.api.app.domain.agent.image_plan_policy import MUTABLE_IMAGE_TOOLS, validate_image_plan
from apps.api.app.domain.agent.memory import AgentMemoryContext
from apps.api.app.domain.agent.plan_policy import AgentPlanPolicyViolation
from apps.api.app.domain.agent.runtime_models import AgentGoalProposal, ToolPlanStep, ModelUsage
from apps.api.app.domain.agent.state_machine import AgentGoalStateMachine
from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError
from apps.api.tests.test_build_plan import plan
from apps.api.tests.test_agent_evidence_observations import conversation, InvocationAccess, Invocations
from apps.api.tests.test_agent_graph_application import InMemoryAgentGraphState


def read_step(**changes):
    return ToolPlanStep(READ_BUILD_PLAN_TOOL, {"project_id": "project", "plan_id": "plan", **changes})


def query_service():
    proposal = plan()
    record = StoredBuildPlan("plan", "project", proposal.digest, "now", proposal)

    class Plans:
        calls = 0
        allowed = True

        def read(self, project_id, plan_id):
            assert (project_id, plan_id) == ("project", "plan")
            self.calls += 1
            if not self.allowed:
                raise PermissionError("plan input revoked")
            return record

    plans = Plans()
    queries = BuildPlanQueryApplicationService(plans)
    request = BuildPlanReadInput(project_id="project", plan_id="plan")
    return queries, plans, queries.execute(request)


def test_plan_receipt_replay_is_pinned_bounded_and_does_not_include_user_content():
    queries, plans, receipt = query_service()
    assert queries.expand(receipt) == plan()
    data = queries.describe(plan(), receipt)
    assert data["work_items"][0]["proposed_tool_id"] == "system_image.build.structure"
    assert data["work_items"][1]["dependency_ids"] == ("structure",)
    assert data["proposed_budget"]["max_tool_calls"] == 80
    assert data["authorization_state"] == "not_granted" and data["execution_ready"] is False
    assert "objective" not in data and "Understand the fixed repository" not in json.dumps(data)
    for field, value in (("plan_digest", "sha256:" + "f" * 64), ("source_manifest_id", "new"),
                         ("source_manifest_hash", "sha256:" + "a" * 64), ("policy_version", "bad")):
        with pytest.raises(BuildPlanIntegrityError):
            queries.expand(receipt.model_copy(update={field: value}))
    plans.allowed = False
    with pytest.raises(PermissionError):
        queries.expand(receipt)


def test_replanner_observes_reauthorized_plan_work_without_implicit_source_egress():
    queries, plans, receipt = query_service()
    invocation = ToolInvocation(id="tool", tool_id=READ_BUILD_PLAN_TOOL, status="completed", summary="verified",
        input_payload={**receipt.request.model_dump(), "goal_template": "system_image_build", "tool_plan_index": 1},
        result=ToolResult(invocation_id="tool", status="completed", summary="verified", build_plan_query=receipt))
    access = InvocationAccess()
    observer = ToolBuildPlanObservationApplicationService(Invocations(invocation), queries, access)
    observations = ToolEvidenceObservationApplicationService(Invocations(invocation), None, access, plans=observer)
    calls = []

    class LLM:
        async def generate_reply(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(mode="live", content='{"action":"keep","rationale":"Review pinned work"}')

    async def memory(_):
        return AgentMemoryContext("system", "context", "history", 0, 0)

    planner = LLMStructuredAgentPlanner(fallback=None, llm=LLM(), tools=[],
        settings_provider=lambda: SimpleNamespace(runtime_mode="live"), custom_api_key_provider=lambda: "",
        memory_context_builder=memory, evidence_observations=observations)
    goal = AgentGoal(id="goal", conversation_id="conversation", project_id="project", planner_kind="llm_structured",
        title="Investigate image", summary="fixed inputs", status="running", steps=[])
    request = AgentReplanRequest(conversation(), goal, "Plan verified", remaining_steps=[read_step()], latest_invocation_id="tool")
    assert asyncio.run(planner.replan(request)).action == "keep"
    data = json.loads(calls[0]["user_message"])["evidence_query_receipt"]
    assert data["plan_digest"] == receipt.plan_digest
    assert data["sources"][0]["source_revision_id"] == "revision"
    assert data["work_items"][0]["binding_state"] == "requires_confirmation"
    assert "Understand the fixed repository" not in calls[0]["user_message"]
    invocation.input_payload["plan_id"] = "foreign"
    with pytest.raises(Exception) as mismatch:
        observer.describe("tool", "project")
    assert mismatch.value.status_code == 409
    invocation.input_payload["plan_id"] = "plan"
    with pytest.raises(Exception) as mismatch:
        observer.describe("tool", "other")
    assert mismatch.value.status_code == 403
    plans.allowed = False
    with pytest.raises(PermissionError, match="revoked"):
        asyncio.run(planner.replan(request))
    assert len(calls) == 1


@pytest.mark.parametrize("tool", sorted(MUTABLE_IMAGE_TOOLS))
def test_pinned_plan_cannot_include_mutable_pipeline_or_publication(tool):
    with pytest.raises(AgentPlanPolicyViolation, match="Pinned investigation"):
        validate_image_plan([read_step(), ToolPlanStep(tool, {"project_id": "project"})])


@pytest.mark.parametrize("field", ["plan_id", "project_id", "plan_digest", "source_manifest_id", "target_baseline_id",
                                  "image_revision_id", "image_artifact_hash"])
def test_pinned_replan_cannot_change_known_binding(field):
    with pytest.raises(AgentPlanPolicyViolation):
        validate_image_plan([read_step(**{field: "old"}), read_step(**{field: "new"})])


def test_goal_target_references_cannot_point_to_another_fixed_plan():
    with pytest.raises(AgentPlanPolicyViolation):
        validate_image_plan([read_step()], ["build_plan:other"])


def graph_fixture(template="system_image_build", replanner=None):
    state = InMemoryAgentGraphState(conversation())
    compiler = AgentGoalPlanCompiler(SimpleNamespace(known_tool_ids=lambda: {READ_BUILD_PLAN_TOOL}))
    graph = LocalAgentGraphRuntime(state, AgentGoalStateMachine(), compiler, replanner)
    proposal = AgentGoalProposal(goal_template=template, title="System image investigation", summary="Inspect fixed plan",
        goal_description="Read and execute the fixed system image plan", planned_tools=[read_step(), read_step()])
    goal = AgentGoal(id="goal", conversation_id="conversation", project_id="project", title=proposal.title,
        summary=proposal.summary, goal_template=template, status="pending", steps=graph.steps_for_proposal(proposal))
    state.goals[goal.id] = goal
    return state, graph, proposal, goal


def test_pinned_goal_never_uses_legacy_state_compiler_or_completes_from_queries():
    state, graph, proposal, goal = graph_fixture()
    assert graph.plan_compiler.compile_followup_tool_plan(goal) == []
    asyncio.run(graph.start(goal.id, proposal))
    assert goal.status == "paused" and goal.pause_reason == "build_completion_review"
    assert {item.tool_id for item in state.invocations.values()} == {READ_BUILD_PLAN_TOOL}
    assert not any(item["metadata"].get("agent_runtime") == "goal_completion" for item in state.messages)
    asyncio.run(graph.resume(goal.id))
    assert goal.status == "paused" and len(state.invocations) == 2
    for target in (replace(proposal, planned_tools=[], target_refs=["build_plan:plan"]),
                   replace(proposal, planned_tools=[], initial_tool_input={"project_id": "project", "source_manifest_id": "manifest"}),
                   replace(proposal, planned_tools=[], goal_template="system_image_investigation")):
        with pytest.raises(AgentPlanPolicyViolation):
            graph.plan_compiler.compile_tool_plan(target)


def test_pure_read_goal_can_complete_without_claiming_build_completion():
    state, graph, proposal, goal = graph_fixture("inspect_plan")
    asyncio.run(graph.start(goal.id, proposal))
    assert goal.status == "completed"


def test_replanner_cannot_drop_input_pins_to_reintroduce_legacy_tools():
    class Replanner:
        async def replan(self, _):
            return AgentReplanDecision("replace_remaining", "Use latest inputs", planned_tools=[
                ToolPlanStep("system_image.context.materialize", {"project_id": "project"})], model_usage=ModelUsage(model_calls=1))

    state, graph, proposal, goal = graph_fixture(replanner=Replanner())
    asyncio.run(graph.start(goal.id, proposal))
    assert {item.tool_id for item in state.invocations.values()} == {READ_BUILD_PLAN_TOOL}
    assert goal.model_calls_used == 1 and goal.status == "paused"
    assert any(item["metadata"].get("planner_kind") == "replan_policy:pinned_image_mutation" for item in state.audits)


def test_restored_mixed_plan_fails_before_any_tool_side_effect():
    state, graph, _, goal = graph_fixture()
    goal.steps[1].selected_tool_id = "system_image.context.materialize"
    outcome = asyncio.run(graph.run_act_node(goal.id, 1))
    assert outcome.route == "end" and goal.status == "failed" and not state.invocations


def test_zero_model_execution_consent_never_calls_model_replanner():
    class NoModel:
        async def replan(self, request):
            pytest.fail("Deterministic build authorization must not call a model replanner")

    _, graph, _, goal = graph_fixture(replanner=NoModel())
    goal.status = "running"
    goal.steps[1].selected_tool_id = "system_image.build.authorize"
    asyncio.run(graph._replan_after_observation(goal, 2, "Execution consent saved"))
    assert goal.model_calls_used == 0


def test_authorized_structure_plan_cannot_smuggle_unapproved_tools():
    with pytest.raises(AgentPlanPolicyViolation, match="capabilities"):
        validate_image_plan([ToolPlanStep("system_image.build.authorize", {"project_id": "p"}),
                             ToolPlanStep("automation.script.generate", {"project_id": "p"})])


def test_verified_receipts_count_new_evidence_not_identical_status_summaries():
    _, _, receipt = query_service()
    _, graph, _, goal = graph_fixture()
    result = ToolResult(invocation_id="tool", status="completed", summary="Plan verified", build_plan_query=receipt)
    invocation = ToolInvocation(id="tool", tool_id=READ_BUILD_PLAN_TOOL, status="completed", summary=result.summary, result=result)
    graph._record_observation_progress(goal, invocation, result.summary)
    assert goal.no_progress_observations == 0
    graph._record_observation_progress(goal, invocation, result.summary)
    assert goal.no_progress_observations == 1
    invocation.result = result.model_copy(update={"build_plan_query": receipt.model_copy(update={"plan_digest": "sha256:" + "f" * 64})})
    graph._record_observation_progress(goal, invocation, result.summary)
    assert goal.no_progress_observations == 0
    graph._record_observation_progress(goal, invocation, result.summary)
    assert goal.no_progress_observations == 1
