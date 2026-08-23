from __future__ import annotations

from types import SimpleNamespace

from apps.api.app.domain.quality_loop.failure_analysis import (
    classify_failure_kind,
    decide_failure_report,
    identify_failure,
)
from apps.api.app.domain.quality_loop.failure_loop_progress import (
    FAILURE_ANALYSIS_NEXT_TOOLS,
    FAILURE_ANALYSIS_SUMMARY,
    FAILURE_BASE_NEXT_TOOLS,
    FAILURE_FALLBACK_NEXT_TOOLS,
    FAILURE_FALLBACK_SUMMARY,
    FAILURE_HEALING_SUMMARY,
    FAILURE_LOOP_PLANNER_KIND,
    decide_failure_loop_progress,
    failure_loop_next_tools,
    failure_loop_summary,
)
from apps.api.app.domain.quality_loop.quality_assets import (
    asset_lane_id,
    default_asset_lane_templates,
    matches_asset_lane,
    next_quality_asset_part_revision,
    quality_asset_pack_current_revision,
    quality_asset_pack_evidence_refs,
    quality_asset_pack_status,
)
from apps.api.app.domain.quality_loop.quality_step_plan import (
    SUPPORTED_DETERMINISTIC_QUALITY_STEPS,
    automation_generation_quality_step_plan,
    automation_quality_step_plan,
    case_quality_step_plan,
    change_document_quality_step_plan,
    deterministic_quality_step_plan,
    release_quality_step_plan,
    scenario_quality_step_plan,
    scope_quality_step_plan,
    verification_plan_quality_step_plan,
)
from apps.api.app.domain.quality_loop.release_readiness import (
    ReleaseReadinessEvidence,
    decide_release_readiness,
)
from apps.api.app.domain.quality_loop.release_decision import (
    decide_release_decision,
    release_decision_id,
    release_decision_status,
)
from apps.api.app.domain.quality_loop.step_guidance import (
    quality_step_assistant_followup,
    quality_step_guidance,
    quality_step_running_summary,
)
from apps.api.app.domain.quality_loop.structured_merge import (
    apply_manual_resolutions,
    three_way_merge,
)
from apps.api.app.domain.quality_loop.us_task_start import (
    US_TASK_ANALYSIS_STATUS,
    US_TASK_MISSING_CONTEXT_NEXT_TOOLS,
    US_TASK_NEXT_ACTION,
    US_TASK_PROGRESS_FLOOR,
    US_TASK_READY_NEXT_TOOLS,
    decide_us_task_item_start,
    decide_us_task_start,
    find_start_task_target,
    requested_or_first_us_id,
)
from apps.api.app.domain.quality_loop.version_risk import (
    DEFAULT_QUALITY_LOOP_NEXT_ACTION,
    PROJECT_PROGRESS_FLOOR_AFTER_RISK_INIT,
    decide_us_risk,
    decide_version_risk,
)
from apps.api.app.domain.quality_loop.version_participants import (
    UNASSIGNED_OWNER,
    decide_us_participant,
    decide_version_participants,
    owner_assignments_from_payload,
)
from apps.api.app.domain.quality_loop.version_us_import import (
    DEFAULT_US_NEXT_ACTION,
    DEFAULT_US_OWNER,
    DEFAULT_US_PROGRESS,
    DEFAULT_US_RISK,
    DEFAULT_US_STATUS,
    decide_version_us_import,
    merge_us_import_item,
    normalize_us_import_item,
    raw_us_items_from_payload,
)


def failure(failure_kind: str, summary: str, *, fallback_to_human: bool = False):
    return SimpleNamespace(
        failure_kind=failure_kind,
        summary=summary,
        fallback_to_human=fallback_to_human,
    )


def release_evidence(
    *,
    failures=(),
    run_statuses=("passed",),
    evidence_types=("trace", "screenshot", "report"),
    asset_part_statuses=(
        ("scenario_set", "approved"),
        ("case_set", "approved"),
        ("automation_blueprint", "completed"),
    ),
    task_context_readiness="ready",
    task_context_confidence=0.9,
    missing_context_count=0,
    quality_profile_coverage=90,
    quality_profile_confidence=0.9,
    fallback_generated_parts=0,
    approvals_open=0,
    pending_merge=0,
):
    return ReleaseReadinessEvidence(
        run_statuses=tuple(run_statuses),
        evidence_types=tuple(evidence_types),
        asset_part_statuses=tuple(asset_part_statuses),
        task_context_readiness=task_context_readiness,
        task_context_confidence=task_context_confidence,
        missing_context_count=missing_context_count,
        quality_profile_coverage=quality_profile_coverage,
        quality_profile_confidence=quality_profile_confidence,
        fallback_generated_parts=fallback_generated_parts,
        open_failures=tuple(failures),
        approvals_open=approvals_open,
        pending_merge=pending_merge,
    )


def failure_report(
    *,
    fingerprint: str = "fp_123",
    healing_attempt_count: int = 0,
    fallback_to_human: bool = False,
):
    return SimpleNamespace(
        failure_fingerprint=fingerprint,
        healing_attempt_count=healing_attempt_count,
        fallback_to_human=fallback_to_human,
    )


def asset_part(part_type: str, status: str, revision: int, evidence_refs: list[str] | None = None):
    return SimpleNamespace(
        part_type=part_type,
        status=status,
        revision=revision,
        evidence_refs=evidence_refs or [],
    )


def failed_run(
    run_id: str = "run_1",
    summary: str = "Run failed",
    *,
    failure_summary: str | None = None,
    evidence: list[str] | None = None,
):
    return SimpleNamespace(
        id=run_id,
        summary=summary,
        failure_summary=failure_summary,
        evidence=evidence or [],
    )


def automation_run(
    *,
    run_id: str = "run_1",
    status: str = "passed",
    task_context_id: str | None = "task_context_1",
    runner_job_id: str | None = "runner_job_1",
    evidence: list[str] | None = None,
):
    return SimpleNamespace(
        id=run_id,
        status=status,
        task_context_id=task_context_id,
        runner_job_id=runner_job_id,
        evidence=evidence if evidence is not None else ["trace", "screenshot"],
    )


def us_item(
    us_id: str,
    *,
    title: str | None = None,
    status: str = "imported",
    risk: str = "low",
    progress: int = 70,
    next_action: str = "",
):
    return SimpleNamespace(
        id=us_id,
        title=title or us_id,
        status=status,
        risk=risk,
        progress=progress,
        next_action=next_action,
    )


def participant_item(us_id: str, *, owner: str = ""):
    return SimpleNamespace(id=us_id, owner=owner)


def release_ready(
    *,
    version_id: str = "ver_1",
    score: int = 86,
    blockers: int = 0,
    approvals_open: int = 0,
    pending_merge: int = 0,
    execution_health: str = "Latest generated automation evidence passed.",
    summary: str = "Release can proceed to review.",
):
    return SimpleNamespace(
        version_id=version_id,
        score=score,
        blockers=blockers,
        approvals_open=approvals_open,
        pending_merge=pending_merge,
        execution_health=execution_health,
        summary=summary,
    )


def deterministic_id_factory(*ids: str):
    values = iter(ids)
    return lambda: next(values)


def test_failure_identity_is_stable_and_uses_sorted_evidence() -> None:
    left = failed_run(failure_summary="Selector drift", evidence=["b", "a"])
    right = failed_run(failure_summary="Selector drift", evidence=["a", "b"])

    assert identify_failure("project_1", "us_1", left) == identify_failure("project_1", "us_1", right)
    identity = identify_failure("project_1", "us_1", left)
    assert identity.report_id == f"failure_run_1_{identity.fingerprint}"
    assert len(identity.fingerprint) == 16


def test_failure_kind_classification_matches_primary_failure_signals() -> None:
    assert classify_failure_kind(failed_run(failure_summary="DOM selector changed")) == "selector"
    assert classify_failure_kind(failed_run(failure_summary="Callback timeout")) == "timeout"
    assert classify_failure_kind(failed_run(failure_summary="Network redirect loop")) == "network"
    assert classify_failure_kind(failed_run(failure_summary="Seed data missing")) == "data"
    assert classify_failure_kind(failed_run(failure_summary="Assertion mismatch")) == "assertion"
    assert classify_failure_kind(failed_run(failure_summary="Unexpected browser state")) == "unknown"


def test_failure_report_decision_tracks_healing_without_fallback() -> None:
    decision = decide_failure_report(
        "project_1",
        "us_1",
        failed_run(failure_summary="DOM selector changed"),
        existing_healing_attempt_count=0,
        increment_healing_attempt=True,
        max_healing_depth=2,
    )

    assert decision.failure_kind == "selector"
    assert decision.status == "healing_proposed"
    assert decision.healing_attempt_count == 1
    assert decision.fallback_to_human is False
    assert decision.run_healing_status == "healing_proposed"
    assert decision.root_cause == "Failure appears tied to selector/assertion drift in the generated automation path."


def test_failure_report_decision_falls_back_at_max_healing_depth() -> None:
    decision = decide_failure_report(
        "project_1",
        "us_1",
        failed_run(failure_summary="Timeout still failing"),
        existing_healing_attempt_count=1,
        increment_healing_attempt=True,
        max_healing_depth=2,
    )

    assert decision.status == "fallback_to_human"
    assert decision.healing_attempt_count == 2
    assert decision.fallback_to_human is True
    assert decision.run_healing_status == "fallback_to_human"
    assert "automatic healing limit" in decision.root_cause


def test_failure_loop_progress_policy_selects_summary_and_next_tools() -> None:
    assert failure_loop_summary(propose_healing=False, fallback_to_human=False) == FAILURE_ANALYSIS_SUMMARY
    assert failure_loop_summary(propose_healing=True, fallback_to_human=False) == FAILURE_HEALING_SUMMARY
    assert failure_loop_summary(propose_healing=True, fallback_to_human=True) == FAILURE_FALLBACK_SUMMARY
    assert failure_loop_next_tools(propose_healing=False, fallback_to_human=False) == list(FAILURE_ANALYSIS_NEXT_TOOLS)
    assert failure_loop_next_tools(propose_healing=True, fallback_to_human=False) == list(FAILURE_BASE_NEXT_TOOLS)
    assert failure_loop_next_tools(propose_healing=True, fallback_to_human=True) == list(FAILURE_FALLBACK_NEXT_TOOLS)


def test_failure_loop_progress_decision_formats_assistant_message_and_metadata() -> None:
    analyze = decide_failure_loop_progress(
        failure_report(fingerprint="abc123", healing_attempt_count=0),
        propose_healing=False,
        max_healing_depth=2,
    )
    healed = decide_failure_loop_progress(
        failure_report(fingerprint="abc123", healing_attempt_count=1),
        propose_healing=True,
        max_healing_depth=2,
    )
    fallback = decide_failure_loop_progress(
        failure_report(fingerprint="abc123", healing_attempt_count=2, fallback_to_human=True),
        propose_healing=True,
        max_healing_depth=2,
    )

    assert analyze.summary == FAILURE_ANALYSIS_SUMMARY
    assert analyze.next_tools == list(FAILURE_ANALYSIS_NEXT_TOOLS)
    assert "abc123" in analyze.assistant_message
    assert "0/2" in analyze.assistant_message
    assert analyze.planner_kind == FAILURE_LOOP_PLANNER_KIND
    assert analyze.fallback_to_human is False
    assert healed.summary == FAILURE_HEALING_SUMMARY
    assert healed.next_tools == list(FAILURE_BASE_NEXT_TOOLS)
    assert fallback.summary == FAILURE_FALLBACK_SUMMARY
    assert fallback.next_tools == list(FAILURE_FALLBACK_NEXT_TOOLS)
    assert fallback.fallback_to_human is True


def test_quality_asset_default_lane_templates_are_stable() -> None:
    templates = default_asset_lane_templates()

    assert [template.lane_key for template in templates] == [
        "scenarios",
        "verification",
        "cases",
        "automation",
        "change_document",
        "release",
    ]
    assert [template.label for template in templates] == [
        "Scenarios",
        "Verification Plan",
        "Cases",
        "Automation",
        "Change Document",
        "Release Assessment",
    ]
    assert all(template.status == "not_started" for template in templates)
    assert templates[0].lane_id("us_1") == "us_1_lane_scenarios"
    assert asset_lane_id("us_1", "release") == "us_1_lane_release"


def test_quality_asset_lane_matching_accepts_legacy_and_canonical_ids() -> None:
    assert matches_asset_lane(lane_id="lane_cases", label="ignored", lane_key="cases")
    assert matches_asset_lane(lane_id="us_1_lane_automation", label="ignored", lane_key="automation")
    assert matches_asset_lane(lane_id="legacy", label="Release Assessment", lane_key="release")
    assert not matches_asset_lane(lane_id="us_1_lane_cases", label="Cases", lane_key="scenarios")


def test_quality_asset_revision_status_and_evidence_policy() -> None:
    draft = asset_part("scope_pack", "draft", 1, ["us:1"])
    scenario = asset_part("scenario_set", "approved", 3, ["scenario:1", "us:1"])

    assert next_quality_asset_part_revision([draft, scenario], "scenario_set") == 4
    assert next_quality_asset_part_revision([draft, scenario], "case_set") == 1
    assert quality_asset_pack_status([draft]) == "draft"
    assert quality_asset_pack_status([draft, scenario]) == "in_review"
    assert quality_asset_pack_current_revision([draft, scenario]) == 3
    assert quality_asset_pack_evidence_refs([draft, scenario]) == ["scenario:1", "us:1"]


def test_quality_asset_pack_completes_when_release_assessment_completes() -> None:
    parts = [
        asset_part("automation_blueprint", "blocked", 2, ["run:1"]),
        asset_part("release_assessment", "completed", 1, ["release:1"]),
    ]

    assert quality_asset_pack_status(parts) == "completed"


def test_quality_step_plan_scope_defines_lane_us_metric_and_asset_updates() -> None:
    plan = scope_quality_step_plan(us_id="us_1")

    assert plan.step == "scope"
    assert plan.summary == "Generated test scope"
    assert plan.object_refs == ("scope_pack:current",)
    assert [(item.lane_key, item.status) for item in plan.lane_updates] == [("scenarios", "ready_for_review")]
    assert plan.us_update.progress == 32
    assert plan.us_update.status == "scope_ready"
    assert plan.us_update.next_action == "Generate scenarios"
    assert plan.metric_update.metric_dict() == {
        "scope_items": 5,
        "regression_focus": 0.76,
        "quality_context_required": True,
        "asset_lane_status": "ready_for_review",
    }
    assert plan.metric_update.evidence_refs == ("scope_pack:current", "us:us_1")
    assert plan.asset_part_update.part_type == "scope_pack"
    assert plan.asset_part_update.status == "ready_for_review"
    assert plan.asset_part_update.evidence_refs == ("scope_pack:current", "us:us_1")
    assert plan.next_tools == ("quality.scenario.generate",)


def test_quality_step_plan_scenario_plan_and_case_follow_v1_progression() -> None:
    scenario = scenario_quality_step_plan(us_id="us_2")
    verification = verification_plan_quality_step_plan(us_id="us_2")
    cases = case_quality_step_plan(us_id="us_2")

    assert SUPPORTED_DETERMINISTIC_QUALITY_STEPS == (
        "scope",
        "scenarios",
        "verification_plan",
        "cases",
        "automation",
        "change_document",
    )
    assert scenario.summary == "Generated scenario pack"
    assert [(item.lane_key, item.status) for item in scenario.lane_updates] == [
        ("scenarios", "approved"),
        ("verification", "ready_for_review"),
    ]
    assert scenario.us_update.progress == 42
    assert scenario.us_update.status == "scenario_ready"
    assert scenario.metric_update.metric_dict()["scenario_groups"] == 8
    assert scenario.asset_part_update.part_type == "scenario_set"
    assert scenario.next_tools == ("quality.plan.generate",)

    assert verification.summary == "Generated verification plan"
    assert [(item.lane_key, item.status) for item in verification.lane_updates] == [
        ("verification", "approved"),
        ("cases", "ready_for_review"),
    ]
    assert verification.us_update.progress == 50
    assert verification.asset_part_update.part_type == "verification_plan"
    assert verification.next_tools == ("quality.case.generate",)

    assert cases.summary == "Generated test case pack"
    assert [(item.lane_key, item.status) for item in cases.lane_updates] == [
        ("cases", "approved"),
        ("automation", "ready_for_review"),
    ]
    assert cases.us_update.progress == 62
    assert cases.us_update.status == "cases_ready"
    assert cases.metric_update.metric_dict()["test_cases"] == 14
    assert cases.metric_update.evidence_refs == (
        "case_set:current",
        "verification_plan:current",
        "scenario_set:current",
        "us:us_2",
    )
    assert cases.asset_part_update.object_refs == (
        "case_set:current",
        "verification_plan:current",
        "scenario_set:current",
    )
    assert cases.next_tools == ("automation.generate",)


def test_deterministic_quality_step_plan_routes_supported_steps_only() -> None:
    assert deterministic_quality_step_plan("scope", us_id="us_1") == scope_quality_step_plan(us_id="us_1")
    assert deterministic_quality_step_plan("scenarios", us_id="us_1") == scenario_quality_step_plan(us_id="us_1")
    assert deterministic_quality_step_plan(
        "verification_plan",
        us_id="us_1",
    ) == verification_plan_quality_step_plan(us_id="us_1")
    assert deterministic_quality_step_plan("cases", us_id="us_1") == case_quality_step_plan(us_id="us_1")
    assert deterministic_quality_step_plan(
        "automation",
        us_id="us_1",
    ) == automation_generation_quality_step_plan(us_id="us_1")
    assert deterministic_quality_step_plan(
        "change_document",
        us_id="us_1",
    ) == change_document_quality_step_plan(us_id="us_1")
    assert deterministic_quality_step_plan("release", us_id="us_1") is None
    assert deterministic_quality_step_plan("unknown", us_id="us_1") is None


def test_automation_generation_plan_stops_before_execution() -> None:
    plan = automation_generation_quality_step_plan(us_id="us_1")

    assert plan.summary == "Generated reviewable Playwright automation blueprint"
    assert plan.object_refs == ("automation_asset:current",)
    assert [(item.lane_key, item.status) for item in plan.lane_updates] == [
        ("automation", "ready_for_review"),
    ]
    assert plan.us_update.status == "automation_ready"
    assert plan.metric_update.metric_dict()["execution_started"] is False
    assert plan.asset_part_update.part_type == "automation_blueprint"
    assert plan.asset_part_update.status == "ready_for_review"
    assert plan.next_tools == ("run.start",)
    assert plan.requires_failure_report is False


def test_automation_quality_step_plan_success_moves_to_change_document() -> None:
    plan = automation_quality_step_plan(
        run=automation_run(status="passed", evidence=["trace"]),
        failed=False,
        runner_mode="local",
        execution_evidence_refs=("execution_evidence:run_1",),
    )

    assert plan.step == "automation"
    assert plan.summary == "Executed automation and captured passing evidence"
    assert plan.object_refs == ("automation_asset:current", "run:run_1")
    assert [(item.lane_key, item.status) for item in plan.lane_updates] == [
        ("automation", "completed"),
        ("change_document", "ready_for_review"),
    ]
    assert plan.us_update.progress == 76
    assert plan.us_update.status == "execution_ready"
    assert plan.us_update.next_action == "Generate quality change document"
    assert plan.metric_update.metric_dict() == {
        "automation_coverage": 0.74,
        "latest_run_status": "passed",
        "runner_mode": "local",
        "runner_job_id": "runner_job_1",
        "task_context_id": "task_context_1",
        "evidence_count": 1,
        "healing_required": False,
    }
    assert plan.metric_update.evidence_refs == ("run:run_1", "execution_evidence:run_1")
    assert plan.asset_part_update.part_type == "automation_blueprint"
    assert plan.asset_part_update.status == "completed"
    assert plan.asset_part_update.evidence_refs == ("execution_evidence:run_1",)
    assert plan.next_tools == ("quality.change-doc.generate",)
    assert plan.requires_failure_report is False


def test_automation_quality_step_plan_failure_blocks_release_and_requests_healing() -> None:
    plan = automation_quality_step_plan(
        run=automation_run(status="failed", task_context_id=None, runner_job_id=None, evidence=[]),
        failed=True,
        runner_mode="local",
        execution_evidence_refs=("execution_evidence:run_failed",),
    )

    assert plan.summary == "Automation execution produced failed runner evidence"
    assert [(item.lane_key, item.status) for item in plan.lane_updates] == [
        ("automation", "blocked"),
        ("release", "blocked"),
    ]
    assert plan.us_update.progress == 72
    assert plan.us_update.status == "execution_failed"
    assert plan.us_update.next_action == "Analyze failed run"
    assert plan.metric_update.metric_dict()["latest_run_status"] == "failed"
    assert plan.metric_update.metric_dict()["runner_job_id"] is None
    assert plan.metric_update.metric_dict()["task_context_id"] is None
    assert plan.metric_update.metric_dict()["evidence_count"] == 0
    assert plan.metric_update.metric_dict()["healing_required"] is True
    assert plan.asset_part_update.status == "blocked"
    assert plan.next_tools == ("healing.propose", "query.run.status")
    assert plan.requires_failure_report is True


def test_release_quality_step_plan_preserves_release_progression_without_blockers() -> None:
    plan = release_quality_step_plan(
        us_id="us_1",
        release=release_ready(version_id="ver_1", score=91),
        release_evidence_refs=("execution_evidence:run_1",),
    )

    assert plan.step == "release"
    assert plan.summary == "Assessed release readiness"
    assert plan.object_refs == ("release_readiness:ver_1",)
    assert [(item.lane_key, item.status) for item in plan.lane_updates] == [("release", "completed")]
    assert plan.us_update.progress == 92
    assert plan.us_update.status == "release_ready"
    assert plan.us_update.next_action == "Request release approval"
    assert plan.metric_update.metric_dict() == {
        "release_score": 91,
        "blockers": 0,
        "approvals_open": 0,
        "pending_merge": 0,
        "execution_health": "Latest generated automation evidence passed.",
    }
    assert plan.metric_update.evidence_refs == (
        "release_readiness:ver_1",
        "execution_evidence:run_1",
        "us:us_1",
    )
    assert plan.asset_part_update.part_type == "release_assessment"
    assert plan.asset_part_update.status == "completed"
    assert plan.asset_part_update.summary == "Release can proceed to review."
    assert plan.asset_part_update.evidence_refs == ("execution_evidence:run_1",)
    assert plan.next_tools == ("approval.request", "query.version.status", "query.governance.status")


def test_release_quality_step_plan_blocks_lane_when_readiness_has_blockers() -> None:
    plan = release_quality_step_plan(
        us_id="us_2",
        release=release_ready(
            version_id="ver_blocked",
            score=58,
            blockers=2,
            approvals_open=1,
            pending_merge=1,
            execution_health="2 open FailureReport(s) require review.",
            summary="Release is blocked.",
        ),
        release_evidence_refs=("release_readiness:ver_blocked",),
    )

    assert [(item.lane_key, item.status) for item in plan.lane_updates] == [("release", "blocked")]
    assert plan.metric_update.metric_dict() == {
        "release_score": 58,
        "blockers": 2,
        "approvals_open": 1,
        "pending_merge": 1,
        "execution_health": "2 open FailureReport(s) require review.",
    }
    assert plan.asset_part_update.status == "completed"
    assert plan.asset_part_update.summary == "Release is blocked."


def test_release_readiness_decision_is_ready_without_open_failures() -> None:
    decision = decide_release_readiness(release_evidence())

    assert decision.status == "Ready for release review"
    assert decision.score >= 90
    assert decision.blockers == 0
    assert decision.approvals_open == 0
    assert decision.pending_merge == 0
    assert decision.progress_floor == 82
    assert decision.execution_health == "1 of 1 automation run(s) passed with 3 persisted evidence type(s)."
    assert decision.blocker_items == []
    assert decision.score == sum(decision.score_breakdown.values())
    assert decision.score_breakdown == {
        "execution": 35,
        "quality_assets": 25,
        "system_context": 18,
        "governance": 20,
        "penalties": 0,
        "policy_adjustment": 0,
    }
    assert decision.evidence_summary["passed_runs"] == 1
    assert decision.evidence_summary["approved_asset_parts"] == 3
    assert decision.to_api_kwargs(version_id="ver_1")["version_id"] == "ver_1"


def test_release_readiness_decision_blocks_on_open_failures() -> None:
    decision = decide_release_readiness(
        release_evidence(
            failures=(
                failure("selector", "Checkout button selector changed"),
                failure("timeout", "Payment callback timed out"),
            )
        )
    )

    assert decision.status == "Blocked by failure analysis"
    assert decision.score == 59
    assert decision.blockers == 2
    assert decision.approvals_open == 0
    assert decision.progress_floor == 76
    assert decision.execution_health == "2 open FailureReport(s) require review; 0 have fallen back to human handling."
    assert decision.blocker_items == [
        "selector: Checkout button selector changed",
        "timeout: Payment callback timed out",
    ]


def test_release_readiness_decision_requires_approval_for_human_fallback() -> None:
    decision = decide_release_readiness(
        release_evidence(
            failures=(
                failure("unknown", "LLM healing exceeded depth", fallback_to_human=True),
            )
        )
    )

    assert decision.status == "Blocked by failure analysis"
    assert decision.score == 39
    assert decision.blockers == 1
    assert decision.approvals_open == 1
    assert "1 have fallen back to human handling" in decision.execution_health


def test_release_readiness_requires_real_run_assets_and_context() -> None:
    decision = decide_release_readiness(ReleaseReadinessEvidence())

    assert decision.status == "Needs additional release evidence"
    assert decision.score < 60
    assert decision.blockers == 3
    assert "No passing automation run" in " ".join(decision.blocker_items)
    assert "Required quality assets" in " ".join(decision.blocker_items)
    assert "TaskContext" in " ".join(decision.blocker_items)
    assert decision.evidence_summary["runs"] == 0


def test_release_readiness_caps_fallback_generation_and_pending_merge() -> None:
    fallback = decide_release_readiness(
        release_evidence(fallback_generated_parts=2)
    )
    pending_merge = decide_release_readiness(
        release_evidence(pending_merge=1)
    )

    assert fallback.status == "Ready for release review"
    assert fallback.score == 84
    assert fallback.score_breakdown["penalties"] == -4
    assert fallback.score_breakdown["policy_adjustment"] < 0
    assert fallback.score == sum(fallback.score_breakdown.values())
    assert pending_merge.status == "Needs additional release evidence"
    assert pending_merge.score <= 69
    assert pending_merge.pending_merge == 1
    assert "merge conflict" in " ".join(pending_merge.blocker_items)


def test_release_decision_policy_resolves_status_id_and_rationale() -> None:
    ready = SimpleNamespace(
        version_id="ver_1",
        score=88,
        blockers=0,
        approvals_open=0,
        pending_merge=0,
    )

    decision = decide_release_decision(
        project_id="project_1",
        us_id="us_1",
        readiness=ready,
        execution_evidence_refs=["execution_evidence:run_1"],
    )

    assert decision.id == release_decision_id("project_1", "ver_1", "us_1")
    assert decision.status == "ready"
    assert decision.evidence_refs == ["release_readiness:ver_1", "execution_evidence:run_1"]
    assert "score=88" in decision.rationale
    assert "evidence_count=1" in decision.rationale


def test_release_decision_policy_blocks_conditions_and_missing_evidence() -> None:
    blocked = SimpleNamespace(version_id="ver_1", score=72, blockers=1, approvals_open=0, pending_merge=0)
    conditional_low_score = SimpleNamespace(
        version_id="ver_1",
        score=79,
        blockers=0,
        approvals_open=0,
        pending_merge=0,
    )
    conditional_gate = SimpleNamespace(version_id="ver_1", score=85, blockers=0, approvals_open=1, pending_merge=0)
    missing_evidence = SimpleNamespace(version_id="ver_1", score=85, blockers=0, approvals_open=0, pending_merge=0)

    assert release_decision_status(blocked, ["execution_evidence:run_1"]) == "blocked"
    assert release_decision_status(conditional_low_score, ["execution_evidence:run_1"]) == "conditional"
    assert release_decision_status(conditional_gate, ["execution_evidence:run_1"]) == "conditional"
    assert release_decision_status(missing_evidence, []) == "needs_evidence"


def test_quality_step_guidance_known_steps_and_fallback_are_stable() -> None:
    assert quality_step_running_summary("scenarios") == "Generating scenario pack"
    assert (
        quality_step_assistant_followup("scenarios")
        == "Next I will turn the approved scenario structure into executable test cases."
    )
    assert quality_step_running_summary("release") == "Assessing release readiness"
    assert (
        quality_step_assistant_followup("release")
        == "The quality loop is ready for human release review or governance follow-up."
    )

    fallback = quality_step_guidance("unknown")
    assert fallback.running_summary == "Running quality-loop tool"
    assert fallback.assistant_followup == "I will continue with the next quality-loop step."


def test_version_us_risk_policy_preserves_v1_thresholds_and_next_action() -> None:
    assert decide_us_risk(us_item("blocked", status="blocked", progress=88)).risk == "high"
    assert decide_us_risk(us_item("failed", status="execution_failed", progress=88)).risk == "high"
    assert decide_us_risk(us_item("early", progress=19)).risk == "high"
    assert decide_us_risk(us_item("medium", progress=59)).risk == "medium"
    assert decide_us_risk(us_item("valid", risk="high", progress=85)).risk == "high"
    assert decide_us_risk(us_item("invalid", risk="unknown", progress=85)).risk == "low"

    fallback = decide_us_risk(us_item("next_action"))
    explicit = decide_us_risk(us_item("explicit", next_action="Generate scope"))

    assert fallback.next_action == DEFAULT_QUALITY_LOOP_NEXT_ACTION
    assert explicit.next_action == "Generate scope"


def test_version_risk_policy_aggregates_project_decision_and_summary() -> None:
    decision = decide_version_risk(
        [
            us_item("us_high", progress=12),
            us_item("us_medium", progress=55),
            us_item("us_low", risk="unknown", progress=85),
        ]
    )

    assert [item.risk for item in decision.item_decisions] == ["high", "medium", "low"]
    assert decision.high_count == 1
    assert decision.medium_count == 1
    assert decision.project_risk == "high"
    assert decision.project_progress_floor == PROJECT_PROGRESS_FLOOR_AFTER_RISK_INIT
    assert decision.summary == "Initialized version risk: 1 high-risk and 1 medium-risk US item(s)."


def test_version_risk_policy_uses_medium_or_low_project_risk_when_no_high_items() -> None:
    medium = decide_version_risk([us_item("us_medium", progress=44)])
    low = decide_version_risk([us_item("us_low", risk="low", progress=90)])

    assert medium.project_risk == "medium"
    assert low.project_risk == "low"


def test_version_participant_payload_parsing_accepts_dict_and_list_shapes() -> None:
    assert owner_assignments_from_payload({"us_1": "Alice", 2: "Bob"}) == {"us_1": "Alice", "2": "Bob"}
    assert owner_assignments_from_payload(
        [
            {"us_id": "us_1", "owner": "Alice"},
            {"id": "us_2", "assignee": "Bob"},
            {"id": "", "owner": "Ignored"},
            "not-a-dict",
        ]
    ) == {"us_1": "Alice", "us_2": "Bob"}
    assert owner_assignments_from_payload(None) == {}


def test_version_participant_policy_prefers_explicit_default_existing_then_unassigned() -> None:
    explicit = decide_us_participant(
        participant_item("us_1", owner="Existing"),
        owner_by_us={"us_1": "Alice"},
        default_owner="Default",
    )
    default = decide_us_participant(
        participant_item("us_2", owner="Existing"),
        owner_by_us={},
        default_owner="Default",
    )
    existing = decide_us_participant(
        participant_item("us_3", owner="Existing"),
        owner_by_us={},
        default_owner="",
    )
    unassigned = decide_us_participant(
        participant_item("us_4"),
        owner_by_us={},
        default_owner="",
    )

    assert explicit.owner == "Alice"
    assert default.owner == "Default"
    assert existing.owner == "Existing"
    assert unassigned.owner == UNASSIGNED_OWNER


def test_version_participant_policy_returns_batch_decisions_and_count() -> None:
    decision = decide_version_participants(
        [participant_item("us_1"), participant_item("us_2", owner="Existing")],
        owner_by_us={"us_1": "Alice"},
        default_owner="",
    )

    assert decision.assigned_count == 2
    assert [(item.us_id, item.owner) for item in decision.item_decisions] == [
        ("us_1", "Alice"),
        ("us_2", "Existing"),
    ]


def test_version_us_import_payload_extraction_prefers_list_keys_and_title_fallback() -> None:
    assert raw_us_items_from_payload({"us_items": [{"id": "us_1"}], "title": "Ignored"}) == [{"id": "us_1"}]
    assert raw_us_items_from_payload({"items": ["Item 1"]}) == ["Item 1"]
    assert raw_us_items_from_payload({"work_items": ["Work item"]}) == ["Work item"]
    assert raw_us_items_from_payload({"inputs": ["Input item"]}) == ["Input item"]
    assert raw_us_items_from_payload({"us_title": "Checkout flow"}) == [{"title": "Checkout flow"}]
    assert raw_us_items_from_payload({}) == []


def test_version_us_import_normalizes_dict_and_text_inputs_with_defaults() -> None:
    dict_item = normalize_us_import_item(
        {"us_id": "us_1", "summary": "Checkout", "progress": "13"},
        index=1,
        id_factory=deterministic_id_factory("unused"),
    )
    text_item = normalize_us_import_item(
        "Plain text US",
        index=2,
        id_factory=deterministic_id_factory("us_generated"),
    )

    assert dict_item.id == "us_1"
    assert dict_item.title == "Checkout"
    assert dict_item.owner == DEFAULT_US_OWNER
    assert dict_item.status == DEFAULT_US_STATUS
    assert dict_item.risk == DEFAULT_US_RISK
    assert dict_item.progress == 13
    assert dict_item.next_action == DEFAULT_US_NEXT_ACTION
    assert text_item.id == "us_generated"
    assert text_item.title == "Plain text US"
    assert text_item.progress == DEFAULT_US_PROGRESS


def test_version_us_import_merge_keeps_highest_progress_and_incoming_defaults() -> None:
    existing = normalize_us_import_item(
        {
            "id": "us_1",
            "title": "Existing title",
            "owner": "Existing owner",
            "status": "analysis",
            "risk": "high",
            "progress": 42,
            "next_action": "Existing next",
        },
        index=1,
        id_factory=deterministic_id_factory("unused"),
    )
    incoming = normalize_us_import_item(
        {"id": "us_1", "progress": 12},
        index=3,
        id_factory=deterministic_id_factory("unused"),
    )

    merged = merge_us_import_item(existing, incoming)

    assert merged.id == "us_1"
    assert merged.title == "Imported US 3"
    assert merged.owner == DEFAULT_US_OWNER
    assert merged.status == DEFAULT_US_STATUS
    assert merged.risk == DEFAULT_US_RISK
    assert merged.progress == 42
    assert merged.next_action == DEFAULT_US_NEXT_ACTION


def test_version_us_import_decision_returns_imported_items_first_then_existing_remainder() -> None:
    existing_items = [
        SimpleNamespace(
            id="us_existing",
            title="Existing",
            owner="QA",
            status="analysis",
            risk="high",
            progress=50,
            next_action="Continue",
        ),
        SimpleNamespace(
            id="us_tail",
            title="Tail",
            owner="Dev",
            status="imported",
            risk="low",
            progress=10,
            next_action="Start",
        ),
    ]

    decision = decide_version_us_import(
        existing_items=existing_items,
        raw_items=[
            {"id": "us_existing", "title": "Updated", "progress": 12},
            "New item",
        ],
        id_factory=deterministic_id_factory("us_new"),
    )

    assert [item.id for item in decision.imported_items] == ["us_existing", "us_new"]
    assert [(item.id, item.title, item.progress) for item in decision.ordered_items] == [
        ("us_existing", "Updated", 50),
        ("us_new", "New item", DEFAULT_US_PROGRESS),
        ("us_tail", "Tail", 10),
    ]


def test_version_us_import_decision_creates_default_item_when_raw_list_empty() -> None:
    decision = decide_version_us_import(
        existing_items=[],
        raw_items=[],
        id_factory=deterministic_id_factory("us_default"),
    )

    assert [(item.id, item.title) for item in decision.imported_items] == [("us_default", "Imported US 1")]


def test_us_task_start_policy_selects_requested_or_first_us() -> None:
    items = [
        us_item("us_1", title="Checkout"),
        us_item("us_2", title="Refund"),
    ]

    assert requested_or_first_us_id(items, "") == "us_1"
    assert requested_or_first_us_id(items, "us_2") == "us_2"
    assert requested_or_first_us_id([], "") == ""
    assert find_start_task_target(items, "us_2") is items[1]
    assert find_start_task_target(items, "") is items[0]
    assert find_start_task_target(items, "missing") is None


def test_us_task_item_start_policy_sets_analysis_state_and_progress_floor() -> None:
    early = decide_us_task_item_start(us_item("us_early", progress=7))
    advanced = decide_us_task_item_start(us_item("us_advanced", progress=54))

    assert early.status == US_TASK_ANALYSIS_STATUS
    assert early.progress == US_TASK_PROGRESS_FLOOR
    assert early.next_action == US_TASK_NEXT_ACTION
    assert advanced.status == US_TASK_ANALYSIS_STATUS
    assert advanced.progress == 54
    assert advanced.next_action == US_TASK_NEXT_ACTION


def test_us_task_start_policy_returns_context_sensitive_next_tools_and_copy() -> None:
    target = us_item("us_checkout", title="Checkout submit", progress=12)
    ready = decide_us_task_start(target, has_task_context=True)
    missing_context = decide_us_task_start(target, has_task_context=False)

    assert ready.summary == "Started quality task for us_checkout."
    assert "Checkout submit" in ready.assistant_message
    assert ready.next_tools == list(US_TASK_READY_NEXT_TOOLS)
    assert ready.requires_followup is False
    assert ready.updated_item.progress == US_TASK_PROGRESS_FLOOR
    assert missing_context.next_tools == list(US_TASK_MISSING_CONTEXT_NEXT_TOOLS)
    assert missing_context.requires_followup is True


def test_three_way_merge_accepts_independent_nested_changes() -> None:
    decision = three_way_merge(
        {"risk": "medium", "coverage": {"api": 60, "ui": 40}},
        {"risk": "high", "coverage": {"api": 60, "ui": 40}},
        {"risk": "medium", "coverage": {"api": 75, "ui": 40}},
    )

    assert decision.ready_for_approval is True
    assert decision.merged_value == {
        "risk": "high",
        "coverage": {"api": 75, "ui": 40},
    }
    assert {patch["path"] for patch in decision.auto_merged_patch} == {"/risk", "/coverage/api"}


def test_three_way_merge_reports_scalar_and_ordered_array_conflicts() -> None:
    decision = three_way_merge(
        {"owner": "qa", "steps": ["open", "submit"]},
        {"owner": "alice", "steps": ["open", "validate", "submit"]},
        {"owner": "bob", "steps": ["submit", "open"]},
    )

    assert decision.ready_for_approval is False
    assert decision.merged_value == {"owner": "qa", "steps": ["open", "submit"]}
    assert [(item.path, item.conflict_kind) for item in decision.conflict_entries] == [
        ("/owner", "scalar"),
        ("/steps", "array"),
    ]
    assert all(item.requires_manual_resolution for item in decision.conflict_entries)


def test_three_way_merge_merges_stable_id_arrays_by_item() -> None:
    decision = three_way_merge(
        [{"id": "case-1", "title": "Pay", "priority": 1}],
        [{"id": "case-1", "title": "Pay securely", "priority": 1}],
        [
            {"id": "case-1", "title": "Pay", "priority": 2},
            {"id": "case-2", "title": "Refund", "priority": 2},
        ],
    )

    assert decision.ready_for_approval is True
    assert decision.merged_value == [
        {"id": "case-1", "title": "Pay securely", "priority": 2},
        {"id": "case-2", "title": "Refund", "priority": 2},
    ]


def test_manual_merge_resolutions_are_path_specific_and_auditable() -> None:
    decision = three_way_merge(
        {"owner": "qa", "notes": "base\ntext"},
        {"owner": "alice", "notes": "left\ntext"},
        {"owner": "bob", "notes": "right\ntext"},
    )
    partially_resolved = apply_manual_resolutions(
        decision,
        {"/owner": {"choice": "left"}},
    )

    assert partially_resolved.ready_for_approval is False
    assert partially_resolved.merged_value["owner"] == "alice"
    assert [item.path for item in partially_resolved.conflict_entries] == ["/notes"]

    resolved = apply_manual_resolutions(
        partially_resolved,
        {"/notes": {"choice": "custom", "value": "reviewed\ntext"}},
    )
    assert resolved.ready_for_approval is True
    assert resolved.merged_value == {"owner": "alice", "notes": "reviewed\ntext"}
    assert [patch["source"] for patch in resolved.auto_merged_patch[-2:]] == ["manual", "manual"]


def test_three_way_merge_preserves_one_sided_deletion() -> None:
    decision = three_way_merge(
        {"obsolete": {"enabled": True}, "stable": 1},
        {"stable": 1},
        {"obsolete": {"enabled": True}, "stable": 1},
    )

    assert decision.ready_for_approval is True
    assert decision.merged_value == {"stable": 1}
    assert decision.auto_merged_patch == [
        {"op": "remove", "path": "/obsolete", "source": "auto"}
    ]


def test_manual_merge_can_select_deleted_candidate() -> None:
    decision = three_way_merge(
        {"owner": "qa"},
        {},
        {"owner": "platform"},
    )

    assert decision.ready_for_approval is False
    resolved = apply_manual_resolutions(
        decision,
        {"/owner": {"choice": "left"}},
    )

    assert resolved.ready_for_approval is True
    assert resolved.merged_value == {}
    assert resolved.auto_merged_patch[-1] == {
        "op": "remove",
        "path": "/owner",
        "source": "manual",
    }
