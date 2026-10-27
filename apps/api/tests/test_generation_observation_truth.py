"""Generation and runner observations are not approval or measured coverage."""
from types import SimpleNamespace

import pytest

from apps.api.app.domain.quality_loop.quality_step_plan import (
    SUPPORTED_DETERMINISTIC_QUALITY_STEPS,
    automation_quality_step_plan,
    deterministic_quality_step_plan,
)
from apps.api.app.domain.system_image.quality_context import (
    automation_feasibility,
    context_confidence,
    coverage_score,
    release_score,
    risk_score,
)


@pytest.mark.parametrize("step", SUPPORTED_DETERMINISTIC_QUALITY_STEPS)
def test_generation_requires_independent_review_and_does_not_invent_quality(step):
    plan = deterministic_quality_step_plan(step, us_id="fixed_us")
    metrics = plan.metric_update.metric_dict()
    assert plan.asset_part_update.status == "ready_for_review"
    assert all(lane.status == "ready_for_review" for lane in plan.lane_updates)
    assert metrics["asset_lane_status"] == "ready_for_review"
    assert metrics["measurement_basis"] == "generated_draft_inventory_not_quality_assessment"
    assert metrics["coverage_status"] == "unknown"
    assert not {"scope_items", "scenario_groups", "risk_edge_groups", "verification_priorities",
        "execution_allocations", "approval_points", "test_cases", "regression_tags", "automation_scripts",
        "change_deltas", "change_risks"}.intersection(metrics), "Counts must come from the validated output"
    assert not {"regression_focus", "scenario_coverage", "assertion_coverage", "automation_coverage"}.intersection(metrics)


@pytest.mark.parametrize("step", SUPPORTED_DETERMINISTIC_QUALITY_STEPS)
def test_generation_observations_cannot_turn_legacy_metrics_into_quality_assessment(step):
    plan = deterministic_quality_step_plan(step, us_id="fixed_us")
    metrics = [SimpleNamespace(metric_group="test_quality", metrics=plan.metric_update.metric_dict()),
        SimpleNamespace(metric_group="code_quality", metrics={"code_risk_score": 0}),
        SimpleNamespace(metric_group="test_quality", metrics={"scenario_coverage": 1, "automation_coverage": 1})]
    assert all(function(metrics) is None for function in (risk_score, coverage_score, automation_feasibility))
    assert release_score(metrics, blocked_items=0, pending_approvals=0) is None
    assert context_confidence([], [], metrics) is None


@pytest.mark.parametrize("failed", [False, True])
def test_actual_runner_outcome_does_not_invent_business_coverage(failed):
    run = SimpleNamespace(id="real_run", status="failed" if failed else "passed", task_context_id="fixed_context",
        runner_job_id="actual_runner_job", evidence=["actual_trace"])
    plan = automation_quality_step_plan(run=run, failed=failed, runner_mode="http_playwright",
        execution_evidence_refs=("execution_evidence:actual_trace",))
    metrics = plan.metric_update.metric_dict()
    assert "automation_coverage" not in metrics
    assert metrics["coverage_status"] == "unknown"
    assert metrics["measurement_basis"] == "runner_observation_not_quality_assessment"
    assert metrics["runner_job_id"] == run.runner_job_id and metrics["latest_run_status"] == run.status
    assert metrics["evidence_count"] == 1
    assert plan.asset_part_update.status == ("blocked" if failed else "completed")
    assert plan.requires_failure_report is failed
