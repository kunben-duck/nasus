from dataclasses import FrozenInstanceError, asdict

import pytest

from apps.api.app.domain.agent.resume_checkpoint import (
    AgentResumeCheckpoint, AgentResumeCheckpointChanged, InvalidAgentResumeCheckpoint,
)
from apps.api.tests.agent_resume_fixtures import paused_goal, resume_transition


def test_resume_digest_is_canonical_immutable_and_does_not_copy_private_inputs():
    payload = paused_goal().model_dump(mode="json")
    payload["steps"][0]["tool_input_payload"]["private_text"] = "private-test-value"
    checkpoint = AgentResumeCheckpoint.capture(payload)
    reordered = dict(reversed(list(payload.items())))
    reordered["steps"][0]["tool_input_payload"] = dict(reversed(list(payload["steps"][0]["tool_input_payload"].items())))
    assert AgentResumeCheckpoint.capture(reordered) == checkpoint
    assert "private-test-value" not in repr(checkpoint) and set(asdict(checkpoint)) == {
        "goal_id", "conversation_id", "project_id", "workflow_id", "digest"}
    with pytest.raises(FrozenInstanceError):
        checkpoint.digest = "sha256:" + "0" * 64


@pytest.mark.parametrize("field,value", [
    ("id", "other"), ("conversation_id", "other"), ("project_id", "other"), ("workflow_id", "other"),
    ("status", "running"), ("pause_reason", "structural_candidate_review"), ("us_id", "other"),
    ("goal_template", "other"), ("goal_description", "changed intent"), ("target_refs", ["plan:other"]),
    ("summary", "changed feedback"), ("autonomy_level", "full_auto"), ("max_steps", 51),
    ("max_model_calls", 33), ("max_thinking_tokens", 500001), ("max_runtime_seconds", 1801),
    ("max_no_progress_observations", 4), ("steps_completed", 1), ("model_calls_used", 1),
    ("thinking_tokens_used", 1), ("no_progress_observations", 1), ("last_progress_fingerprint", "other"),
])
def test_resume_digest_pins_scope_plan_intent_and_budget(field, value):
    payload = paused_goal().model_dump(mode="json")
    checkpoint = AgentResumeCheckpoint.capture(payload)
    payload[field] = value
    with pytest.raises(AgentResumeCheckpointChanged, match="checkpoint changed"):
        checkpoint.require_matches(payload)


@pytest.mark.parametrize("field,value", [
    ("id", "different_step"), ("phase", "observing"), ("status", "completed"),
    ("selected_tool_id", "system_image.build.structure"), ("tool_invocation_id", "different_invocation"),
    ("tool_input_payload", {"image_revision_id": "different_image"}), ("tool_target_scope", "edge"),
    ("decision", "continue"), ("memory_context_hash", "different_context"),
])
def test_resume_digest_pins_the_exact_step_and_tool_inputs(field, value):
    payload = paused_goal().model_dump(mode="json")
    checkpoint = AgentResumeCheckpoint.capture(payload)
    payload["steps"][0][field] = value
    with pytest.raises(AgentResumeCheckpointChanged):
        checkpoint.require_matches(payload)


@pytest.mark.parametrize("status", ["draft", "pending", "running", "completed", "failed", "cancelled"])
def test_only_paused_checkpoints_can_be_captured(status):
    payload = paused_goal().model_dump(mode="json")
    payload["status"] = status
    with pytest.raises(InvalidAgentResumeCheckpoint):
        AgentResumeCheckpoint.capture(payload)


@pytest.mark.parametrize("change", ["missing", "extra", "nan", "non_json", "oversized", "step_count"])
def test_malformed_or_unbounded_resume_snapshots_fail_closed(change):
    payload = paused_goal().model_dump(mode="json")
    if change == "missing":
        del payload["max_steps"]
    elif change == "extra":
        payload["new_control_field"] = "requires a versioned contract"
    elif change == "nan":
        payload["steps"][0]["tool_input_payload"]["value"] = float("nan")
    elif change == "non_json":
        payload["steps"][0]["tool_input_payload"]["value"] = object()
    elif change == "oversized":
        payload["summary"] = "private-test-value" * 40000
    else:
        payload["steps"] *= 513
    with pytest.raises(InvalidAgentResumeCheckpoint) as error:
        AgentResumeCheckpoint.capture(payload)
    assert "private-test-value" not in str(error.value)


def test_resume_transition_must_consume_the_paused_state_without_rebinding_scope():
    goal = paused_goal()
    checkpoint = AgentResumeCheckpoint.capture(goal.model_dump(mode="json"))
    checkpoint.require_matches(goal.model_dump(mode="json"))
    checkpoint.require_transition(resume_transition(goal).model_dump(mode="json"))
    with pytest.raises(InvalidAgentResumeCheckpoint):
        checkpoint.require_transition(goal.model_dump(mode="json"))
    foreign = resume_transition(goal)
    foreign.project_id = "foreign"
    with pytest.raises(AgentResumeCheckpointChanged):
        checkpoint.require_transition(foreign.model_dump(mode="json"))


@pytest.mark.parametrize("digest", ["sha256:" + "0 " * 32, "sha256:" + "A" * 64, "sha256:" + "z" * 64])
def test_checkpoint_digest_requires_canonical_sha256(digest):
    with pytest.raises(InvalidAgentResumeCheckpoint):
        AgentResumeCheckpoint("goal", "conversation", None, None, digest)


def test_queue_payload_round_trips_only_the_five_fixed_precondition_fields():
    checkpoint = AgentResumeCheckpoint.capture(paused_goal().model_dump(mode="json"))
    assert AgentResumeCheckpoint.from_payload(checkpoint.payload()) == checkpoint
    for changed in ({**checkpoint.payload(), "confirmed": True}, {"digest": checkpoint.digest}, None):
        with pytest.raises(InvalidAgentResumeCheckpoint):
            AgentResumeCheckpoint.from_payload(changed)
