import asyncio
from types import SimpleNamespace

import pytest

from apps.api.app.domain.agent.resume_checkpoint import AgentResumeCheckpoint, AgentResumeCheckpointChanged
from apps.api.app.application.agent.activities import AgentWorkflowActivityApplicationService
from apps.api.app.application.agent.loop import AgentLoopRuntime
from apps.api.app.infrastructure.config.agent_runtime_config import TemporalGatewayConfig
from apps.api.app.infrastructure.workflow.agent_goal_workflow_worker import AgentGoalWorkflowActivityService
from apps.api.app.infrastructure.workflow.nasus_agent_goal_workflow import NasusAgentGoalWorkflow
from apps.api.app.infrastructure.workflow.temporal_agent_gateway import TemporalClientWorkflowGateway
from apps.api.app.infrastructure.workflow.langgraph_agent_gateway import LangGraphAgentLoopGateway
from apps.api.tests.agent_resume_fixtures import paused_goal


def test_temporal_signal_pins_exact_checkpoint_and_replay_never_schedules_another_resume():
    goal = paused_goal()
    checkpoint = AgentResumeCheckpoint.capture(goal.model_dump(mode="json"))
    calls, consumed = [], []
    current = goal.model_copy(deep=True)

    async def query(*args):
        return current.model_dump(mode="json")

    async def signal(name, payload):
        calls.append((name, payload))
        current.pause_reason = "build_completion_review"
        consumed.append(checkpoint.digest)

    handle = SimpleNamespace(query=query, signal=signal)

    async def factory(config):
        return SimpleNamespace(get_workflow_handle=lambda _: handle)

    gateway = TemporalClientWorkflowGateway(TemporalGatewayConfig(query_timeout_seconds=1),
        client_factory=factory, workflow_id_provider=lambda _: goal.workflow_id,
        goal_state_reader=lambda _: current, resume_replay_reader=lambda value: value.digest in consumed,
        goal_state_sink=lambda _: pytest.fail("A Temporal cursor must not overwrite PG facts"))
    result = asyncio.run(gateway.resume_goal(goal.id, expected_resume=checkpoint))
    assert result.pause_reason == "build_completion_review"
    assert calls[0][1]["expected_resume"] == checkpoint.payload()
    assert asyncio.run(gateway.resume_goal(goal.id, expected_resume=checkpoint)) == current
    assert len(calls) == 1


def test_stale_temporal_precondition_is_rejected_before_signalling():
    goal = paused_goal()
    checkpoint = AgentResumeCheckpoint.capture(goal.model_dump(mode="json"))
    goal.max_steps += 1

    async def unavailable(config):
        pytest.fail("Stale request must not reach Temporal")

    gateway = TemporalClientWorkflowGateway(client_factory=unavailable, goal_state_reader=lambda _: goal)
    with pytest.raises(AgentResumeCheckpointChanged):
        asyncio.run(gateway.resume_goal(goal.id, expected_resume=checkpoint))


@pytest.mark.parametrize("template", ["system_image_build", "system_image_investigation"])
@pytest.mark.parametrize("status", ["paused", "blocked"])
def test_temporal_completion_review_is_a_noop_before_query_or_signal(template, status):
    goal = paused_goal()
    goal.goal_template, goal.status = template, status
    goal.pause_reason = "build_completion_review"
    original = goal.model_dump(mode="json")
    checkpoint = AgentResumeCheckpoint.capture(original)

    async def unavailable(config):
        pytest.fail("Settled completion review must not query or signal Temporal")

    gateway = TemporalClientWorkflowGateway(client_factory=unavailable,
        goal_state_reader=lambda _: goal, resume_replay_reader=lambda _: False,
        goal_state_sink=lambda _: pytest.fail("Review cannot overwrite authoritative facts"))
    for _ in range(3):
        assert asyncio.run(gateway.resume_goal(goal.id, expected_resume=checkpoint)).model_dump(mode="json") == original
    with pytest.raises(AgentResumeCheckpointChanged):
        asyncio.run(gateway.resume_goal(goal.id,
            expected_resume=AgentResumeCheckpoint.capture({**original, "max_steps": goal.max_steps + 1})))


def test_temporal_completion_review_without_pg_reader_does_not_signal():
    goal = paused_goal()
    goal.goal_template, goal.pause_reason = "system_image_build", "build_completion_review"
    checkpoint = AgentResumeCheckpoint.capture(goal.model_dump(mode="json"))
    queries = []

    async def query(*args):
        queries.append(args)
        return goal.model_dump(mode="json")

    async def signal(*args):
        pytest.fail("Completion review is not executable work")

    async def factory(config):
        return SimpleNamespace(get_workflow_handle=lambda _: SimpleNamespace(query=query, signal=signal))

    gateway = TemporalClientWorkflowGateway(client_factory=factory, workflow_id_provider=lambda _: goal.workflow_id)
    assert asyncio.run(gateway.resume_goal(goal.id, expected_resume=checkpoint)) == goal
    assert len(queries) == 1


def test_worker_passes_queued_pin_and_conflict_is_not_an_infinitely_retrying_activity():
    goal = paused_goal()
    checkpoint = AgentResumeCheckpoint.capture(goal.model_dump(mode="json"))
    calls = []

    async def resume(goal_id, *, expected_resume):
        calls.append((goal_id, expected_resume))
        raise AgentResumeCheckpointChanged()

    application = SimpleNamespace(resume_goal=resume, get_goal=lambda _: goal)
    worker = AgentGoalWorkflowActivityService(activity_application_provider=lambda: application)
    response = asyncio.run(worker.resume_agent_goal({"goal_id": goal.id, "expected_resume": checkpoint.payload()}))
    assert calls == [(goal.id, checkpoint)]
    assert response["_resume_error"] == "agent_checkpoint_changed" and response["id"] == goal.id
    with pytest.raises(AgentResumeCheckpointChanged):
        TemporalClientWorkflowGateway._goal_from_payload(response, goal.workflow_id)


@pytest.mark.parametrize("payload", [[], "bad", {}, {"unknown": True}, {"digest": "bad"}])
def test_worker_rejects_malformed_queued_checkpoint_without_retrying_or_resuming(payload):
    goal = paused_goal()

    async def resume(*args, **kwargs):
        pytest.fail("Malformed preconditions must never release a gate")

    worker = AgentGoalWorkflowActivityService(activity_application_provider=lambda:
        SimpleNamespace(resume_goal=resume, get_goal=lambda _: goal))
    response = asyncio.run(worker.resume_agent_goal({"goal_id": goal.id, "expected_resume": payload}))
    assert response["_resume_error"] == "agent_checkpoint_invalid"
    assert response["id"] == goal.id


def test_a_previous_temporal_rejection_does_not_block_a_new_valid_checkpoint():
    goal = paused_goal()
    checkpoint = AgentResumeCheckpoint.capture(goal.model_dump(mode="json"))
    projection = {**goal.model_dump(mode="json"), "_resume_error": "agent_checkpoint_changed"}
    calls = []

    async def query(*args):
        return dict(projection)

    async def signal(name, payload):
        calls.append(payload)
        projection.pop("_resume_error")
        projection["pause_reason"] = "build_completion_review"

    async def factory(config):
        return SimpleNamespace(get_workflow_handle=lambda _: SimpleNamespace(query=query, signal=signal))

    gateway = TemporalClientWorkflowGateway(TemporalGatewayConfig(query_timeout_seconds=1), client_factory=factory)
    result = asyncio.run(gateway.resume_goal(goal.id, expected_resume=checkpoint))
    assert result.pause_reason == "build_completion_review"
    assert calls == [{"goal_id": goal.id, "expected_resume": checkpoint.payload()}]


def test_an_unpinned_worker_signal_cannot_release_a_fixed_image_gate():
    goal = paused_goal()

    async def resume(*args, **kwargs):
        pytest.fail("A bare signal must not enter the graph for a fixed image goal")

    loop = AgentLoopRuntime(SimpleNamespace(get_goal=lambda _: goal), SimpleNamespace(resume=resume))
    application = AgentWorkflowActivityApplicationService(loop_runtime=loop, goal_projector=None)
    worker = AgentGoalWorkflowActivityService(activity_application_provider=lambda: application)
    result = asyncio.run(worker.resume_agent_goal({"goal_id": goal.id}))
    assert result["_resume_error"] == "agent_checkpoint_invalid"
    assert result["pause_reason"] == goal.pause_reason


def test_an_unpinned_legacy_goal_retains_its_worker_contract():
    goal = paused_goal()
    goal.target_refs = []
    goal.steps[0].selected_tool_id = "quality.generate.scenarios"
    goal.steps[0].tool_input_payload = {}
    calls = []

    async def resume(goal_id):
        calls.append(goal_id)
        return goal

    loop = AgentLoopRuntime(SimpleNamespace(get_goal=lambda _: goal), SimpleNamespace(resume=resume))
    assert asyncio.run(loop.resume_goal(goal.id)) == goal
    assert calls == [goal.id]


def test_workflow_duplicate_signal_cannot_become_a_next_gate_confirmation():
    goal = paused_goal()
    checkpoint = AgentResumeCheckpoint.capture(goal.model_dump(mode="json"))
    workflow = NasusAgentGoalWorkflow()
    workflow._current_goal = goal.model_dump(mode="json")
    payload = {"goal_id": goal.id, "expected_resume": checkpoint.payload(), "actor": {"original": True}}
    asyncio.run(workflow.resume_goal(payload))
    assert workflow._resume_payload == payload
    workflow._resume_requested = False
    workflow._resume_payload = {}
    asyncio.run(workflow.resume_goal({**payload, "actor": {"different": True}}))
    assert not workflow._resume_requested and not workflow._resume_payload


def test_langgraph_resume_explicitly_resets_the_durable_precondition_between_requests():
    goal = paused_goal()
    checkpoint = AgentResumeCheckpoint.capture(goal.model_dump(mode="json"))
    calls = []

    async def ainvoke(state, **kwargs):
        calls.append(state)
        return state

    gateway = LangGraphAgentLoopGateway(SimpleNamespace(get_goal=lambda _: goal), None, None,
        compiled_graph=SimpleNamespace(ainvoke=ainvoke))
    asyncio.run(gateway.resume(goal.id, expected_resume=checkpoint))
    asyncio.run(gateway.resume(goal.id))
    assert calls[0]["expected_resume"] == checkpoint.payload()
    assert "expected_resume" in calls[1] and calls[1]["expected_resume"] is None
