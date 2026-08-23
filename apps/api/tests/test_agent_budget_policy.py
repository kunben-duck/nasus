from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from apps.api.app.domain.agent.budget_policy import (
    evaluate_agent_budget,
    observation_progress_fingerprint,
    record_model_usage,
    record_observation_progress,
)
from apps.api.app.domain.agent.runtime_models import ModelUsage


def _goal(**overrides):
    values = {
        "max_steps": 50,
        "max_model_calls": 32,
        "max_thinking_tokens": 500_000,
        "max_runtime_seconds": 1_800,
        "max_no_progress_observations": 3,
        "steps_completed": 0,
        "model_calls_used": 0,
        "thinking_input_tokens_used": 0,
        "thinking_output_tokens_used": 0,
        "thinking_tokens_used": 0,
        "no_progress_observations": 0,
        "started_at": None,
        "last_progress_at": None,
        "last_progress_fingerprint": None,
        "budget_exhausted_reason": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_model_usage_updates_all_durable_counters():
    goal = _goal()

    record_model_usage(
        goal,
        ModelUsage(
            model_calls=1,
            input_tokens=120,
            output_tokens=30,
            usage_source="provider",
        ),
    )

    assert goal.model_calls_used == 1
    assert goal.thinking_input_tokens_used == 120
    assert goal.thinking_output_tokens_used == 30
    assert goal.thinking_tokens_used == 150


def test_budget_policy_reports_specific_model_token_and_runtime_limits():
    assert evaluate_agent_budget(
        _goal(model_calls_used=2, max_model_calls=2)
    ).reason == "max_model_calls"
    assert evaluate_agent_budget(
        _goal(thinking_tokens_used=100, max_thinking_tokens=100)
    ).reason == "max_thinking_tokens"

    now = datetime.now(timezone.utc)
    runtime = evaluate_agent_budget(
        _goal(
            started_at=(now - timedelta(seconds=31)).isoformat(),
            max_runtime_seconds=30,
        ),
        now=now,
    )
    assert runtime.reason == "max_runtime_seconds"
    assert "31/30s" in runtime.summary


def test_repeated_observation_fingerprint_trips_no_progress_budget_and_resets_on_change():
    goal = _goal(max_no_progress_observations=2)
    first = observation_progress_fingerprint(
        tool_id="quality.scope.generate",
        status="completed",
        summary="No new evidence",
        object_refs=["scope:one"],
    )
    changed = observation_progress_fingerprint(
        tool_id="quality.scope.generate",
        status="completed",
        summary="New evidence materialized",
        object_refs=["scope:two"],
    )

    assert record_observation_progress(
        goal,
        fingerprint=first,
        occurred_at="2026-07-30T00:00:00+00:00",
    )
    assert not record_observation_progress(
        goal,
        fingerprint=first,
        occurred_at="2026-07-30T00:00:01+00:00",
    )
    assert not record_observation_progress(
        goal,
        fingerprint=first,
        occurred_at="2026-07-30T00:00:02+00:00",
    )
    assert evaluate_agent_budget(goal).reason == "max_no_progress_observations"

    assert record_observation_progress(
        goal,
        fingerprint=changed,
        occurred_at="2026-07-30T00:00:03+00:00",
    )
    assert goal.no_progress_observations == 0
    assert evaluate_agent_budget(goal).exhausted is False


def test_observation_fingerprint_is_order_independent_for_evidence_refs():
    left = observation_progress_fingerprint(
        tool_id="run.execute",
        status="completed",
        summary="Finished",
        evidence_refs=["evidence:b", "evidence:a"],
    )
    right = observation_progress_fingerprint(
        tool_id="run.execute",
        status="completed",
        summary="Finished",
        evidence_refs=["evidence:a", "evidence:b"],
    )

    assert left == right
