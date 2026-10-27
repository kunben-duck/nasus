import pytest

from apps.api.app.domain.system_image.build_completion import assess_build_completion, completion_digest
from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError, propose_build_plan, BuildBudgetProposal
from apps.api.app.domain.system_image.investigation import propose_investigation
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.tests.test_build_plan import manifest
from apps.api.tests.test_investigation import artifact


def inputs(purpose="structure"):
    proposal = propose_build_plan(manifest(), objective="Inspect the repository", mode="initialize", purpose=purpose, budget=BuildBudgetProposal())
    review = propose_investigation(proposal, "image", artifact(proposal), ())
    scans = [{"source_revision_id": "revision", "binding_id": "code", "source_type": "code",
        "manifest_hash": snapshot_digest("source"), "inventory_hash": snapshot_digest("inventory"),
        "enumeration_complete": True, "file_count": 1, "excluded_entries": 2,
        "failed_entries": 0, "unsupported_entries": 0, "file_bodies_verified": False}]
    checkpoint = {"project_id": "project", "goal_template": "system_image_build", "status": "paused",
        "model_calls_used": 0, "thinking_tokens_used": 0, "steps_completed": 4, "active_runtime_ms": 1200}
    return proposal, review, scans, checkpoint


def test_verified_members_do_not_invent_delivery_budget_conflicts_or_coverage():
    proposal, review, scans, checkpoint = inputs()
    report = assess_build_completion(proposal, review, scans, [], checkpoint, 12)
    assert report["state"] == "blocked" and report["delivery_kind"] == "candidate_only"
    assert not any(report[key] for key in ("candidate_ready", "goal_completed", "publication_authorized", "execution_authorized"))
    assert report["readiness"]["structure"]["verified_evidence_count"] == 12
    assert all(value["coverage"] is None for value in report["readiness"].values())
    assert report["budget"]["cost_microusd"] is None and not report["budget"]["full_plan_accounting_verified"]
    assert report["critical_conflicts"]["count"] is None
    assert {"full_plan_budget_unverified", "critical_conflicts_unverified", "gap_ownership_unassigned",
            "full_source_bytes_unverified", "code_analysis_not_selected"} <= set(report["blockers"])
    assert all(item["owner_actor_id"] is None for item in report["gaps"])
    assert report["source_scans"][0]["excluded_entries"] == 2
    assert completion_digest(report) == completion_digest(assess_build_completion(proposal, review, scans, [], checkpoint, 12))


@pytest.mark.parametrize("purpose", ["behavior", "traceability"])
def test_structure_does_not_satisfy_required_semantic_artifact(purpose):
    proposal, review, scans, checkpoint = inputs(purpose)
    report = assess_build_completion(proposal, review, scans, [], checkpoint, 12)
    assert "required_artifact_unverified" in report["blockers"]
    assert any(item["artifact"] == "proposed_behavior_and_links" and item["state"] == "unverified" for item in report["required_artifacts"])


@pytest.mark.parametrize("change,blocker", [({"enumeration_complete": False}, "source_inventory_incomplete"),
    ({"failed_entries": 1}, "source_acquisition_gaps"), ({"unsupported_entries": 1}, "source_acquisition_gaps")])
def test_capture_gaps_are_not_hidden_by_member_counts(change, blocker):
    proposal, review, scans, checkpoint = inputs()
    report = assess_build_completion(proposal, review, [{**scans[0], **change}], [], checkpoint, 12)
    assert blocker in report["blockers"]


@pytest.mark.parametrize("status", ["partial", "unknown", "complete"])
def test_fixed_analysis_does_not_attest_build_lineage(status):
    proposal, review, scans, checkpoint = inputs()
    analysis = {"source_revision_id": "revision", "analysis_id": "analysis", "report_hash": snapshot_digest("analysis"),
        "failed": 0, "not_analyzed": 0, "unsupported": 1, "projection_status": status}
    report = assess_build_completion(proposal, review, scans, [analysis], checkpoint, 12)
    assert ("code_analysis_partial" in report["blockers"]) == (status != "complete")
    assert "analysis_build_lineage_unverified" in report["blockers"]
    assert report["code_analyses"][0]["unsupported"] == 1


@pytest.mark.parametrize("change", [{"project_id": "foreign"}, {"status": "running"}, {"status": "completed"},
    {"active_started_at": "2026-10-08T00:00:00Z"}, {"goal_template": "other"}])
def test_other_scope_or_live_checkpoint_is_not_completion_evidence(change):
    proposal, review, scans, checkpoint = inputs()
    with pytest.raises(BuildPlanIntegrityError):
        assess_build_completion(proposal, review, scans, [], {**checkpoint, **change}, 12)


def test_omitted_foreign_or_duplicate_source_inventory_is_rejected():
    proposal, review, scans, checkpoint = inputs()
    for changed in ([], [*scans, *scans], [{**scans[0], "binding_id": "foreign"}],
                    [{**scans[0], "source_revision_id": "foreign"}]):
        with pytest.raises(BuildPlanIntegrityError):
            assess_build_completion(proposal, review, changed, [], checkpoint, 12)
