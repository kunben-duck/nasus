"""Assessment completion cannot promote unknown or insufficient evidence."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.domain.quality_loop.quality_step_plan import release_quality_step_plan
from apps.api.app.domain.quality_loop.release_readiness import (
    ReleaseReadinessEvidence,
    decide_release_readiness,
    meets_release_review_threshold,
)


def readiness(**changes):
    return SimpleNamespace(**{
        "version_id": "version", "status": "Ready for release review", "score": 90,
        "blockers": 0, "approvals_open": 0, "pending_merge": 0,
        "execution_health": "Persisted passing observations", "summary": "Original assessment",
        "evidence_summary": {"quality_assessment_unknown": 0}, **changes,
    })


@pytest.mark.parametrize("changes", [
    {"score": value} for value in (-1, 0, 59, 79, 101, True, 80.0, "80", None)
] + [
    {"status": "Needs additional release evidence"},
    {"status": "Blocked by failure analysis"}, {"status": None},
] + [
    {"blockers": value} for value in (1, -1, False)
])
def test_invalid_assessment_never_advances_release_stage(changes):
    original = readiness(**changes)
    before = deepcopy(vars(original))
    assert not meets_release_review_threshold(original)
    plan = release_quality_step_plan(us_id="us", release=original,
        release_evidence_refs=("execution_evidence:original",))
    assert plan.us_update.status == "blocked" and plan.us_update.progress == 70
    assert plan.asset_part_update.status == "blocked"
    assert plan.lane_updates[0].status == "blocked"
    assert "approval.request" not in plan.next_tools
    assert plan.metric_update.metric_dict()["release_score"] == original.score
    assert plan.metric_update.evidence_refs == (
        "release_readiness:version", "execution_evidence:original", "us:us")
    assert vars(original) == before


@pytest.mark.parametrize("changes", [
    {"approvals_open": 1}, {"pending_merge": 1}, {"approvals_open": False}, {"pending_merge": -1},
    {"evidence_summary": {"quality_assessment_unknown": 1}},
    {"evidence_summary": {"quality_assessment_unknown": False}},
    {"evidence_summary": {"quality_assessment_unknown": "0"}},
    {"evidence_summary": None},
])
def test_pending_or_unknown_evidence_cannot_be_hidden_by_high_score(changes):
    original = readiness(**changes)
    assert not meets_release_review_threshold(original)
    plan = release_quality_step_plan(us_id="us", release=original, release_evidence_refs=())
    assert plan.us_update.status == "blocked" and "approval.request" not in plan.next_tools


@pytest.mark.parametrize("score", [80, 90, 100])
def test_valid_known_assessment_preserves_release_review_path(score):
    original = readiness(score=score)
    assert meets_release_review_threshold(original, version_id="version")
    assert not meets_release_review_threshold(original, version_id="different-version")
    plan = release_quality_step_plan(us_id="us", release=original, release_evidence_refs=())
    assert plan.us_update.status == "release_ready" and plan.asset_part_update.status == "completed"
    assert "approval.request" in plan.next_tools
    assert plan.metric_update.metric_dict()["release_score"] == score


def test_missing_assessment_is_not_release_ready():
    assert not meets_release_review_threshold(None)
    assert not meets_release_review_threshold(SimpleNamespace())


def test_real_scoring_policy_and_release_stage_share_the_same_threshold():
    evidence = ReleaseReadinessEvidence(run_statuses=("passed",), evidence_types=("trace", "log", "result"),
        asset_part_statuses=(("scenario_set", "approved"), ("case_set", "approved"),
            ("automation_blueprint", "completed")), task_context_readiness="ready",
        task_context_confidence=1, quality_profile_coverage=100, quality_profile_confidence=1)
    known = decide_release_readiness(evidence)
    assert meets_release_review_threshold(known)
    unknown = decide_release_readiness(ReleaseReadinessEvidence(**{
        **vars(evidence), "task_context_confidence": None, "quality_profile_coverage": None}))
    assert not meets_release_review_threshold(unknown)
    assert unknown.evidence_summary["quality_assessment_unknown"] == 1
    assert unknown.score <= 59 and unknown.blockers == 1
    assert release_quality_step_plan(us_id="us", release=SimpleNamespace(**unknown.to_api_kwargs(version_id="version")),
        release_evidence_refs=()).us_update.status == "blocked"
