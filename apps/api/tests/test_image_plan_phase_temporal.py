"""Actual Temporal phase continuation with PG/MinIO; no target execution."""
import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from temporalio.client import Client, WorkflowFailureError
from temporalio.worker import Replayer, Worker

from apps.api.app.application.agent.activities import AgentWorkflowActivityApplicationService
from apps.api.app.application.agent.graph import LocalAgentGraphRuntime
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.domain.agent.resume_checkpoint import AgentResumeCheckpoint
from apps.api.app.domain.agent.runtime_models import AgentGoalProposal, ToolPlanStep
from apps.api.app.infrastructure.config.agent_runtime_config import TemporalGatewayConfig
from apps.api.app.infrastructure.persistence.build_authorization_models import BuildAuthorizationRecord
from apps.api.app.infrastructure.persistence.build_tool_budget_repository import BuildToolBudgetRepository
from apps.api.app.infrastructure.persistence.db_models import AgentGoalRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.structure_build_models import StructureBuildArtifactRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.workflow.agent_goal_workflow_worker import (
    AgentGoalWorkflowActivityService, build_agent_goal_activity_definitions,
)
from apps.api.app.infrastructure.workflow.nasus_agent_goal_workflow import NasusAgentGoalWorkflow
from apps.api.app.infrastructure.workflow.temporal_agent_gateway import TemporalClientWorkflowGateway
from apps.api.app.store import get_runtime_assembly
from apps.api.tests.test_agent_investigation_continuation import acting, replace_graph
from apps.api.tests.test_build_plan_revision_api import confirm
from apps.api.tests.test_image_plan_phase_api import activation, current_goal, phases, prepare_phase, revised
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_structure_build_api import request
from apps.api.tests.test_targeted_build_intent_api import fixed_request


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="requires an explicitly enabled local Temporal server")
@pytest.mark.parametrize("targeted,shared", [(False, False), (True, False), (True, True)],
    ids=["legacy", "targeted", "shared-entry"])
def test_real_temporal_phase_retry_and_worker_replacement_do_not_release_its_new_budget(evidence_api, monkeypatch, tmp_path, targeted, shared):
    v = evidence_api
    replace_graph(monkeypatch, "langgraph_postgres")
    assembly = get_runtime_assembly()
    state = assembly.agent_application_ports.workflow_state
    activities = AgentWorkflowActivityApplicationService(loop_runtime=assembly.agent_loop_runtime,
        goal_projector=assembly.agent_goal_projection)
    service = AgentGoalWorkflowActivityService(activity_application_provider=lambda: activities)
    definitions = build_agent_goal_activity_definitions(service)
    fixed = fixed_request(v)[0] if targeted else request(v)
    root_url = f"/v1/projects/{v['project_id']}/system-image/build-plans/{fixed['plan_id']}"
    original_update = LocalAgentGraphRuntime._update_goal
    crashes = []

    async def crash_after_phase_consumption(self, goal, *, patch, expected_resume=None):
        await original_update(self, goal, patch=patch, expected_resume=expected_resume)
        if patch.get("resume_mode") == "image_plan_phase_prepared" and not crashes:
            crashes.append(expected_resume.digest)
            raise RuntimeError("injected activity failure after atomic phase resume consumption")

    monkeypatch.setattr(LocalAgentGraphRuntime, "_update_goal", crash_after_phase_consumption)

    async def verify():
        client = await Client.connect(os.environ["TEST_TEMPORAL_ADDRESS"])
        config = TemporalGatewayConfig(address=os.environ["TEST_TEMPORAL_ADDRESS"],
            task_queue="nasus-test-phase-" + uuid4().hex, query_timeout_seconds=60)

        async def factory(_):
            return client

        gateway = TemporalClientWorkflowGateway(config, client_factory=factory,
            workflow_id_provider=state.workflow_id_for_goal, goal_state_reader=state.get_goal,
            resume_replay_reader=state.is_resume_consumed)
        proposal = AgentGoalProposal(goal_template="system_image_build", title="Temporal source enrichment",
            summary="Preserve original facts through phase continuation", target_refs=[f"build_plan:{fixed['plan_id']}"],
            goal_description="Enrich the same original goal without reusing execution consent",
            planned_tools=[ToolPlanStep("system_image.build.structure", fixed)])
        if shared:
            proposal.target_refs = [f"project:{v['project_id']}", f"build_plan:{fixed['plan_id']}",
                f"build_plan_digest:{fixed['plan_digest']}"]
            proposal.planned_tools = []
        handle = None
        try:
            async with Worker(client, task_queue=config.task_queue, workflows=[NasusAgentGoalWorkflow], activities=definitions):
                with actor_scope(UserProfile.model_validate(v["owner"])):
                    started = await gateway.start_goal(v["conversation"].json()["id"], proposal)
                    handle = client.get_workflow_handle(started.workflow_id)
                    if shared:
                        planned = [step.selected_tool_id for step in started.steps if step.phase == "acting"]
                        assert planned == ["query.system_image.build_plans.read", "system_image.build.authorize", "system_image.build.structure"]
                    original = await gateway.resume_goal(started.id,
                        expected_resume=AgentResumeCheckpoint.capture(started.model_dump(mode="json")))
                    assert original.pause_reason == "structural_candidate_review"
            prefix = original.model_dump(mode="json")["steps"]
            original_budget, original_work = BuildToolBudgetRepository().inspect(started.id)
            assert {item["invocation_id"] for item in original_work} == {
                step["tool_invocation_id"] for step in prefix
                if step["phase"] == "acting" and step["selected_tool_id"] and step["tool_invocation_id"]}
            assert_completed_work(original_work)
            old_plan = v["client"].get(root_url, headers=v["headers"]).json()
            assert original_budget.max_tool_calls == old_plan["proposal"]["intent"]["budget"]["max_tool_calls"]
            if targeted:
                assert old_plan["proposal"]["policy_version"] == "nasus.image-investigation-plan.v3"
            revision = revised(v, fixed, original.model_dump(mode="json"), tmp_path)
            command = confirm(v, prepare_phase(v, activation(v, fixed, original.model_dump(mode="json"), revision)))
            assert command["status"] == "completed", command
            prepared = current_goal(v, original.model_dump(mode="json"))
            assert prepared["pause_reason"] == "build_plan_phase_prepared"
            assert prepared["steps"][:len(prefix)] == prefix
            phase, = phases(v, fixed, prepared).json()
            new_plan_id = phase["phase"]["plan_id"]

            def assert_unexecuted():
                with session_scope() as session:
                    assert session.scalar(select(func.count()).select_from(BuildAuthorizationRecord)
                        .where(BuildAuthorizationRecord.goal_id == started.id, BuildAuthorizationRecord.plan_id == new_plan_id)) == 0
                    assert session.scalar(select(func.count()).select_from(StructureBuildArtifactRecord)
                        .where(StructureBuildArtifactRecord.plan_id == new_plan_id)) == 0

            assert_unexecuted()
            pin = AgentResumeCheckpoint.capture(prepared)
            replace_graph(monkeypatch, "langgraph_postgres")
            async with Worker(client, task_queue=config.task_queue, workflows=[NasusAgentGoalWorkflow], activities=definitions):
                with actor_scope(UserProfile.model_validate(v["owner"])):
                    pending = await gateway.resume_goal(started.id, expected_resume=pin)
                    assert crashes == [pin.digest] and state.is_resume_consumed(pin)
                    assert pending.pause_reason == "waiting_confirmation"
                    pending_budget, pending_work = BuildToolBudgetRepository().inspect(started.id)
                    assert pending_budget == original_budget
                    assert pending_work[:len(original_work)] == original_work
                    assert len(pending_work) == len(original_work) + 3
                    assert {item["invocation_id"] for item in pending_work[len(original_work):-1]} == {
                        revision["revision"]["invocation_id"], command["id"]}
                    assert pending.model_dump(mode="json")["steps"][:len(prefix)] == prefix
                    blocked, = [step for step in pending.model_dump(mode="json")["steps"][len(prefix):]
                        if step["phase"] == "acting" and step["status"] == "blocked"]
                    assert blocked["selected_tool_id"] == "system_image.build.authorize"
                    assert blocked["tool_input_payload"]["plan_id"] == new_plan_id
                    assert_unexecuted()
                    # Deliver a duplicate to the real workflow, not just the API gateway.
                    await handle.signal(config.resume_signal, {"goal_id": started.id, "expected_resume": pin.payload(),
                        "actor": {"user": v["owner"]}})
                    await asyncio.sleep(.3)
                    assert state.get_goal(started.id) == pending
                    assert await gateway.resume_goal(started.id, expected_resume=pin) == pending
                    assert BuildToolBudgetRepository().inspect(started.id) == (pending_budget, pending_work)
                    assert_unexecuted()

            replace_graph(monkeypatch, "langgraph_postgres")
            async with Worker(client, task_queue=config.task_queue, workflows=[NasusAgentGoalWorkflow], activities=definitions):
                with actor_scope(UserProfile.model_validate(v["owner"])):
                    executed = await gateway.resume_goal(started.id,
                        expected_resume=AgentResumeCheckpoint.capture(pending.model_dump(mode="json")))
                    assert executed.pause_reason == "structural_candidate_review"
                    assert executed.model_dump(mode="json")["steps"][:len(prefix)] == prefix
                    with session_scope() as session:
                        grants = session.scalars(select(BuildAuthorizationRecord).where(
                            BuildAuthorizationRecord.goal_id == started.id, BuildAuthorizationRecord.plan_id == new_plan_id)).all()
                        assert len(grants) == 1 and grants[0].authorization_invocation_id == blocked["tool_invocation_id"]
                        if targeted:
                            assert grants[0].payload["target_baseline_id"] == old_plan["proposal"]["intent"]["target"]["target_baseline_id"]
                        assert session.scalar(select(func.count()).select_from(StructureBuildArtifactRecord)
                            .where(StructureBuildArtifactRecord.plan_id == new_plan_id)) == 1
                        assert session.scalar(select(func.count()).select_from(AgentGoalRecord)
                            .where(AgentGoalRecord.conversation_id == original.conversation_id)) == 1
                    assert v["client"].get(root_url, headers=v["headers"]).json() == old_plan
                    investigation = await gateway.resume_goal(started.id,
                        expected_resume=AgentResumeCheckpoint.capture(executed.model_dump(mode="json")))
                    assert investigation.pause_reason == "waiting_confirmation"
                    assert acting(investigation.model_dump(mode="json"))[-1]["selected_tool_id"] == "system_image.build.investigate"
                    reviewed = await gateway.resume_goal(started.id,
                        expected_resume=AgentResumeCheckpoint.capture(investigation.model_dump(mode="json")))
                    assert reviewed.pause_reason == "build_completion_review" and reviewed.model_calls_used == 0
                    assert reviewed.model_dump(mode="json")["steps"][:len(prefix)] == prefix
                    assert await gateway.resume_goal(started.id, expected_resume=pin) == reviewed
                    assert phases(v, fixed, reviewed.model_dump(mode="json")).json() == [phase]
                    final_budget, final_work = BuildToolBudgetRepository().inspect(started.id)
                    assert final_budget == original_budget and final_work[:len(original_work)] == original_work
                    assert {item["invocation_id"] for item in final_work} == {
                        step.tool_invocation_id for step in reviewed.steps
                        if step.phase == "acting" and step.selected_tool_id and step.tool_invocation_id
                    } | {revision["revision"]["invocation_id"], command["id"]}
                    assert_completed_work(final_work)
                history = await handle.fetch_history()
            replay = await Replayer(workflows=[NasusAgentGoalWorkflow]).replay_workflow(history)
            assert replay.replay_failure is None
            assert BuildToolBudgetRepository().inspect(started.id) == (final_budget, final_work)
        finally:
            if handle is not None:
                await handle.cancel()
                async with Worker(client, task_queue=config.task_queue, workflows=[NasusAgentGoalWorkflow], activities=definitions):
                    with pytest.raises(WorkflowFailureError):
                        await asyncio.wait_for(handle.result(), 15)

    asyncio.run(verify())


def assert_completed_work(entries):
    # A completed command may leave its AgentStep blocked for independent review.
    with session_scope() as session:
        assert all(session.get(ToolInvocationRecord, item["invocation_id"]).status == "completed" for item in entries)
