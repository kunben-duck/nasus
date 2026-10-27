"""Waiting for mandatory inputs retains the target, never structural consent."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.agent.agent_models import AgentGoal, AgentStep
from apps.api.app.application.agent.graph import LocalAgentGraphRuntime
from apps.api.app.application.agent.plans import AgentGoalPlanCompiler
from apps.api.app.application.agent.source_build_wait import WAIT_REF, WAIT_REASON, WAIT_TOOL, wait_refs
from apps.api.app.application.system_image.build_preparation import BuildPreparationRequired
from apps.api.app.domain.agent.plan_policy import AgentPlanPolicyViolation
from apps.api.app.domain.agent.resume_checkpoint import AgentResumeCheckpoint
from apps.api.app.domain.agent.state_machine import AgentGoalStateMachine
from apps.api.tests.test_natural_build_entries import fixture, conversation, request_refs


def waiting_fixture():
    v = fixture()
    v.plans.manifests.latest_manifest = lambda _: None
    proposal = v.entries.plan(conversation(), "Build the system image").agent_goal
    tool = v.entries.compile(proposal)[0]
    goal = AgentGoal(id="goal", conversation_id="conversation", project_id="project", title="Wait", summary="Fixed",
        goal_template="system_image_build", status="paused", pause_reason=WAIT_REASON, target_refs=proposal.target_refs,
        steps=[AgentStep(id="think", title="Think", phase="thinking", status="completed"),
            AgentStep(id="wait", title="Wait", phase="acting", status="blocked", selected_tool_id=tool.tool_id,
                tool_input_payload=tool.input_payload, tool_invocation_id="status"),
            AgentStep(id="observe", title="Observe", phase="observing", status="pending"),
            AgentStep(id="decide", title="Decide", phase="deciding", status="pending")])
    receipt = SimpleNamespace(id="status", conversation_id="conversation", tool_id=WAIT_TOOL, status="completed",
        input_payload={**deepcopy(tool.input_payload), "agent_goal_id": "goal"},
        result=SimpleNamespace(invocation_id="status", status="completed", object_refs=["project:project"]))
    v.invocations.get_tool_invocation = lambda ident: receipt
    compiler = AgentGoalPlanCompiler(SimpleNamespace(known_tool_ids=lambda: {WAIT_TOOL, "system_image.build.plan",
        "query.system_image.build_plans.read", "system_image.build.authorize", "system_image.build.structure"}), build_intents=v.entries)
    return SimpleNamespace(**locals())


def test_missing_code_retains_one_read_only_command_and_unchanged_target():
    w = waiting_fixture()
    assert len(w.proposal.target_refs) == 3 and w.proposal.target_refs[-1].startswith(WAIT_REF)
    assert [tool.tool_id for tool in w.compiler.compile_tool_plan(w.proposal)] == [WAIT_TOOL]
    w.compiler.validate_goal_plan(w.goal)
    with pytest.raises(BuildPreparationRequired, match="code source"):
        w.compiler.compile_source_input_continuation(w.goal)
    assert w.goal.pause_reason == WAIT_REASON


@pytest.mark.parametrize("change", ["objective", "target", "extra", "refs", "receipt-goal", "receipt-conversation",
    "receipt-payload", "receipt-status", "receipt-result", "receipt-project", "additional-work", "revoked", "target-moved"])
def test_waiting_scope_and_original_command_are_verified_before_continuing(change):
    w = waiting_fixture()
    w.v.plans.manifests.latest_manifest = lambda _: w.v.source
    payload = w.goal.steps[1].tool_input_payload["build_input_request"]
    if change == "objective": payload["objective"] = "Different"
    if change == "target": payload["target"]["target_baseline_id"] = "other"
    if change == "extra": payload["publish"] = True
    if change == "refs": w.goal.target_refs.append("project:other")
    if change == "receipt-goal": w.receipt.input_payload["agent_goal_id"] = "other"
    if change == "receipt-conversation": w.receipt.conversation_id = "other"
    if change == "receipt-payload": w.receipt.input_payload["build_input_request"]["objective"] = "Other"
    if change == "receipt-status": w.receipt.status = "running"
    if change == "receipt-result": w.receipt.result.invocation_id = "other"
    if change == "receipt-project": w.receipt.result.object_refs = ["project:other"]
    if change == "additional-work": w.goal.steps.insert(-1, AgentStep(id="extra", title="Extra", phase="acting",
        status="pending", selected_tool_id="system_image.context.materialize", tool_input_payload={"project_id": "project"}))
    if change == "revoked": w.v.plans.authorization.scope = lambda _: (_ for _ in ()).throw(PermissionError("PRIVATE"))
    if change == "target-moved": w.v.plans.require_target_current = lambda _: (_ for _ in ()).throw(ValueError("PRIVATE"))
    with pytest.raises(AgentPlanPolicyViolation) as failure:
        w.compiler.compile_source_input_continuation(w.goal)
    assert "PRIVATE" not in str(failure.value)


def test_capture_fixes_sources_without_replacing_wait_request_or_granting_budget():
    w = waiting_fixture()
    before = deepcopy(w.goal.steps[1].tool_input_payload)
    w.v.plans.manifests.latest_manifest = lambda _: w.v.source
    refs, tools = w.compiler.compile_source_input_continuation(w.goal)
    request = w.v.preparations.waiting.continuation(w.goal)
    assert refs == [*request_refs(request), w.proposal.target_refs[-1]]
    assert [tool.tool_id for tool in tools] == ["system_image.build.plan"]
    assert tools[0].input_payload["target"] == before["build_input_request"]["target"]
    assert w.goal.target_refs == w.proposal.target_refs and w.goal.steps[1].tool_input_payload == before
    prepared = w.v.entries.plan(conversation(), "Build the system image for this project.").agent_goal
    w.v.entries.require_preparation_reuse(prepared, w.goal)
    with pytest.raises(AgentPlanPolicyViolation):
        w.v.entries.require_preparation_reuse(replace(prepared, initial_tool_input={**prepared.initial_tool_input,
            "objective": "Another objective"}), w.goal)


def test_missing_inputs_do_not_consume_resume_or_confirm_a_tool():
    w = waiting_fixture()
    writes = []
    state = SimpleNamespace(get_goal=lambda _: w.goal.model_copy(deep=True), is_resume_consumed=lambda _: False,
        persist_goal_at_checkpoint=lambda *args: writes.append(args),
        confirm_tool_invocation=lambda _: pytest.fail("Input capture is not tool confirmation"))
    graph = LocalAgentGraphRuntime(state, AgentGoalStateMachine(), w.compiler)
    checkpoint = AgentResumeCheckpoint.capture(w.goal.model_dump(mode="json"))
    assert asyncio.run(graph.prepare_resume(w.goal.id, expected_resume=checkpoint)).route == "end"
    assert writes == [] and w.goal.pause_reason == WAIT_REASON


def test_status_wait_answer_has_no_model_egress_but_ordinary_query_keeps_its_reply():
    from apps.api.app.application.platform.query_tools import QueryToolApplicationService
    w = waiting_fixture()
    replies = []
    async def reply(**kwargs):
        replies.append(kwargs)
        return SimpleNamespace(content="model answer", metadata={})
    service = object.__new__(QueryToolApplicationService)
    service._read_model = SimpleNamespace(get_conversation=lambda _: conversation())
    service._agent_replies = SimpleNamespace(generate_reply=reply)
    plan = SimpleNamespace(fallback_text="local status", planner_kind="query", user_message="status", prompt_id="status")
    assert asyncio.run(service.answer(w.receipt, plan)).content == "local status" and replies == []
    del w.receipt.input_payload["build_input_request"]
    assert asyncio.run(service.answer(w.receipt, plan)).content == "model answer" and len(replies) == 1
