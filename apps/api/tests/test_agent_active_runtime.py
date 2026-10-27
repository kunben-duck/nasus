"""Active analysis excludes human waits without resetting spent runtime."""
from datetime import datetime, timedelta, timezone
import asyncio
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.api.app.application.agent.agent_models import AgentGoal, AgentStep
from apps.api.app.application.agent.lifecycle import AgentGoalLifecycleApplicationService
from apps.api.app.domain.agent.active_runtime import settle_active_runtime
from apps.api.app.domain.agent.budget_policy import evaluate_agent_budget
from apps.api.app.domain.agent.resume_checkpoint import AgentResumeCheckpoint, AgentResumeCheckpointChanged, InvalidAgentResumeCheckpoint
from apps.api.app.domain.agent.state_machine import AgentGoalStateMachine
from apps.api.tests.agent_resume_fixtures import paused_goal
from apps.api.tests.test_agent_budget_policy import _goal


START = datetime(2026, 10, 8, tzinfo=timezone.utc)


def tracked_goal(**overrides):
    return AgentGoal(id="clock-goal", conversation_id="clock-conversation", title="Active analysis",
        status="pending", summary="Waits are not work", steps=[AgentStep(id="clock-step", title="Work", status="pending")],
        active_runtime_ms=0, **overrides)


def test_paused_tracked_goal_does_not_exhaust_runtime_after_two_days():
    goal = _goal(started_at=START.isoformat(), active_runtime_ms=500, active_started_at=None, max_runtime_seconds=1)
    assert not evaluate_agent_budget(goal, now=START + timedelta(days=2)).exhausted


def test_active_interval_and_spent_milliseconds_both_count():
    goal = _goal(started_at=(START - timedelta(days=2)).isoformat(), active_runtime_ms=750,
        active_started_at=START.isoformat(), max_runtime_seconds=1)
    assert not evaluate_agent_budget(goal, now=START + timedelta(milliseconds=249)).exhausted
    assert evaluate_agent_budget(goal, now=START + timedelta(milliseconds=250)).reason == "max_runtime_seconds"


@pytest.mark.parametrize("transition", ["gate", "budget", "followup", "failure", "cancel", "complete"])
def test_every_pause_or_terminal_transition_settles_the_active_interval_once(transition):
    clock = SimpleNamespace(now=START)
    machine = AgentGoalStateMachine(clock=lambda: clock.now)
    goal = tracked_goal()
    machine.start_goal(goal)
    clock.now += timedelta(milliseconds=125)
    actions = {
        "gate": lambda: machine.pause_on_gate(goal, 0, "waiting_confirmation"),
        "budget": lambda: machine.pause_on_budget(goal, 0, reason="max_steps", summary="Spent steps"),
        "followup": lambda: machine.pause_on_followup(goal, 0, "missing_captured_code", "Capture code"),
        "failure": lambda: machine.fail_on_step(goal, 0, "Failed"),
        "cancel": lambda: machine.cancel_on_step(goal, 0, "Cancelled"),
        "complete": lambda: machine.complete_goal(goal, 0),
    }
    actions[transition]()
    assert goal.active_runtime_ms == 125 and goal.active_started_at is None
    clock.now += timedelta(days=2)
    actions[transition]()
    assert goal.active_runtime_ms == 125 and goal.active_started_at is None


def test_resume_preserves_first_start_and_accumulates_short_intervals():
    clock = SimpleNamespace(now=START)
    machine = AgentGoalStateMachine(clock=lambda: clock.now)
    goal = tracked_goal(max_runtime_seconds=1)
    for _ in range(8):
        machine.start_goal(goal)
        original_start = goal.active_started_at
        clock.now += timedelta(milliseconds=50)
        machine.start_goal(goal)
        assert goal.active_started_at == original_start
        clock.now += timedelta(milliseconds=75)
        machine.pause_on_gate(goal, 0, "waiting_confirmation")
        clock.now += timedelta(days=2)
    assert goal.started_at == START.isoformat() and goal.active_runtime_ms == 1000
    assert evaluate_agent_budget(goal, now=clock.now).reason == "max_runtime_seconds"


def test_user_interrupt_persists_a_settled_clock_before_publishing(monkeypatch):
    goal = tracked_goal()
    AgentGoalStateMachine(clock=lambda: START).start_goal(goal)
    persisted, published = [], []
    async def publish(value):
        assert persisted == [value.model_dump(mode="json")]
        published.append(value.active_runtime_ms)
    state = SimpleNamespace(get_goal=lambda _: goal, persist_goal=lambda value: persisted.append(value.model_dump(mode="json")),
        record_goal_audit=lambda *args, **kwargs: None, publish_interrupted=publish)
    monkeypatch.setattr("apps.api.app.application.agent.lifecycle.settle_active_runtime",
        lambda value: settle_active_runtime(value, now=START + timedelta(milliseconds=625)))
    result = asyncio.run(AgentGoalLifecycleApplicationService(state, None).interrupt_goal(goal.id))
    assert result.status == "paused" and result.pause_reason == "user_interrupt"
    assert result.active_runtime_ms == 625 and result.active_started_at is None and published == [625]


def test_an_unsettled_running_interval_survives_process_reconstruction():
    goal = tracked_goal(max_runtime_seconds=1)
    machine = AgentGoalStateMachine(clock=lambda: START)
    machine.start_goal(goal)
    reloaded = AgentGoal.model_validate_json(goal.model_dump_json())
    machine.start_goal(reloaded)
    assert reloaded.active_started_at == START.isoformat()
    assert evaluate_agent_budget(reloaded, now=START + timedelta(seconds=1)).reason == "max_runtime_seconds"


def test_legacy_json_and_checkpoint_digest_are_not_rewritten():
    goal = paused_goal()
    payload = goal.model_dump(mode="json")
    assert "active_runtime_ms" not in payload and "active_started_at" not in payload
    encoded = json.dumps({"schema": "nasus.agent-resume-checkpoint.v1", "goal": payload},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    assert AgentResumeCheckpoint.capture(payload).digest == "sha256:" + sha256(encoded).hexdigest()
    assert AgentGoal.model_validate_json(goal.model_dump_json()).model_dump(mode="json") == payload


def test_new_checkpoint_pins_active_runtime_and_rejects_a_counter_change():
    goal = tracked_goal()
    goal.status = "paused"
    payload = goal.model_dump(mode="json")
    assert payload["active_runtime_ms"] == 0 and payload["active_started_at"] is None
    checkpoint = AgentResumeCheckpoint.capture(payload)
    encoded = json.dumps({"schema": "nasus.agent-resume-checkpoint.v2", "goal": payload},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    assert checkpoint.digest == "sha256:" + sha256(encoded).hexdigest()
    with pytest.raises(AgentResumeCheckpointChanged):
        checkpoint.require_matches({**payload, "active_runtime_ms": 1})
    with pytest.raises(InvalidAgentResumeCheckpoint):
        checkpoint.require_transition({**payload, "status": "running"})
    checkpoint.require_transition({**payload, "status": "running", "active_started_at": START.isoformat()})


@pytest.mark.parametrize("fields", [
    {"active_runtime_ms": -1}, {"active_runtime_ms": True}, {"active_runtime_ms": 1.5},
    {"active_runtime_ms": "5"}, {"active_runtime_ms": 2**63},
    {"active_started_at": START.isoformat()},
    {"active_runtime_ms": 0, "active_started_at": "not-a-time"},
    {"active_runtime_ms": 0, "active_started_at": "2026-10-08T00:00:00"},
])
def test_malformed_clock_is_rejected_instead_of_disabling_budget(fields):
    with pytest.raises(ValidationError):
        AgentGoal(id="bad-clock", conversation_id="conversation", title="Bad clock", status="paused", summary="", steps=[], **fields)
