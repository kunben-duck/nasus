"""Pure append-only phase policy checks, without a database or workflow engine."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.agent.agent_models import AgentGoal, AgentStep
from apps.api.app.application.agent.image_plan_phases import phase_steps
from apps.api.app.domain.agent.image_plan_phases import (
    ImagePlanPhase, PHASE_PREPARED, PHASE_REF, active_phase_start, phase_contract,
    phase_target_refs, verify_phase_chain,
)
from apps.api.app.domain.agent.plan_policy import AgentPlanPolicyViolation
from apps.api.app.domain.agent.resume_checkpoint import AgentResumeCheckpoint
from apps.api.app.domain.agent.state_machine import AgentGoalStateMachine
from apps.api.app.domain.system_image.build_authorization import ApprovedBuildBudget
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest


HASH = "sha256:" + "a" * 64


def prepared_phase():
    goal = AgentGoal(id="goal", conversation_id="conversation", project_id="project", title="Original goal",
        goal_template="system_image_build", status="paused", summary="Preserve original source pins",
        target_refs=["build_plan:root"], pause_reason="structural_candidate_review", steps=[
            AgentStep(id="original", title="Await original structure review", phase="acting", status="blocked",
                selected_tool_id="system_image.build.structure", tool_input_payload={"project_id": "project",
                    "plan_id": "root", "plan_digest": HASH, "target_baseline_id": "baseline"})])
    budget = ApprovedBuildBudget(max_tool_calls=1, max_model_calls=0, max_active_seconds=600, max_cost_microusd=0)
    request = SimpleNamespace(budget=SimpleNamespace(model_dump=lambda: {
        "max_tool_calls": 1, "max_model_calls": 0, "max_active_seconds": 600, "max_cost_microusd": 0}))
    steps = phase_steps(goal, "phase", request, SimpleNamespace(plan_id="revised", plan_digest=HASH), "baseline")
    phase = ImagePlanPhase(phase_id="phase", project_id="project", goal_id="goal", root_plan_id="root",
        revision_id="revision", revision_hash=HASH, plan_id="revised", plan_digest=HASH,
        source_manifest_id="manifest", source_manifest_hash=HASH, target_baseline_id="baseline", target_version_id=None,
        parent_phase_id=None, parent_phase_hash=None, phase_number=1, start_index=1,
        prefix_hash=snapshot_digest([step.model_dump(mode="json") for step in goal.steps]),
        contracts=tuple(phase_contract(step) for step in steps), budget=budget,
        checkpoint=AgentResumeCheckpoint.capture(goal.model_dump(mode="json")), invocation_id="activation", created_at="2026-10-07T00:00:00+00:00")
    goal.steps.extend([AgentStep(id=PHASE_REF + phase.phase_id, title="Prepared phase", phase="deciding", status="completed",
        tool_input_payload=phase.marker()), *steps])
    goal.target_refs.append(PHASE_REF + phase.phase_id)
    goal.pause_reason = PHASE_PREPARED
    return goal, phase


def test_active_phase_skips_original_review_and_keeps_fixed_plan_scope():
    goal, phase = prepared_phase()
    assert verify_phase_chain(goal, [phase]) == active_phase_start(goal) == 2
    assert phase_target_refs(goal) == ["project:project", "build_plan:revised", "source_manifest:manifest"]
    assert AgentGoalStateMachine.blocked_act_step_index(goal) is None
    assert AgentGoalStateMachine.current_step_index(goal) == 2
    goal.steps[4].status = "blocked"
    assert AgentGoalStateMachine.blocked_act_step_index(goal) == 4
    assert verify_phase_chain(goal, [phase]) == 2


@pytest.mark.parametrize("changed", ["original", "marker", "marker_status", "contract", "order", "orphan", "active", "duplicate", "root"])
def test_changed_goal_cannot_reuse_an_immutable_phase(changed):
    goal, phase = prepared_phase()
    if changed == "original":
        goal.steps[0].title = "Changed history"
    elif changed == "marker":
        goal.steps[1].tool_input_payload["phase_hash"] = "sha256:" + "b" * 64
    elif changed == "marker_status":
        goal.steps[1].status = "pending"
    elif changed == "contract":
        goal.steps[4].tool_input_payload["budget"]["max_model_calls"] = 1
    elif changed == "order":
        goal.steps[2], goal.steps[4] = goal.steps[4], goal.steps[2]
    elif changed == "orphan":
        goal.steps[1].id = "unregistered-marker"
    elif changed == "active":
        goal.target_refs.append("build_plan_phase:another")
    elif changed == "duplicate":
        goal.steps[-1].id = goal.steps[2].id
    else:
        goal.target_refs.remove("build_plan:root")
    with pytest.raises(AgentPlanPolicyViolation):
        verify_phase_chain(goal, [phase])


@pytest.mark.parametrize("changed", [{"phase_number": 2}, {"goal_id": "other"}, {"start_index": 504},
    {"parent_phase_id": "parent"}, {"policy_version": "unverified"}, {"contracts": ()}])
def test_invalid_phase_receipt_is_not_an_execution_contract(changed):
    goal, phase = prepared_phase()
    with pytest.raises(AgentPlanPolicyViolation):
        verify_phase_chain(goal, [replace(phase, **changed)])


def test_missing_durable_receipt_does_not_make_phase_markers_authoritative():
    goal, _ = prepared_phase()
    with pytest.raises(AgentPlanPolicyViolation):
        verify_phase_chain(goal, [])
