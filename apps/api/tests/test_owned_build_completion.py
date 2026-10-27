from copy import deepcopy
from dataclasses import replace

import pytest
from pydantic import ValidationError

from apps.api.app.application.system_image.build_completions import BuildCompletionInput, CompletionOwnershipPin
from apps.api.app.domain.system_image.build_completion import assess_build_completion
from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError
from apps.api.app.domain.system_image.gap_ownership import GapResponsibility, report_gaps
from apps.api.app.domain.system_image.owned_build_completion import CompletionOwnershipProof, assess_owned_completion
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.tests.agent_resume_fixtures import paused_goal
from apps.api.tests.test_build_completion import inputs


def original_and_proof():
    plan, review, scans, checkpoint = inputs()
    report = assess_build_completion(plan, review, scans, [], checkpoint, 12)
    report.update(schema="nasus.image-build-completion.v2", build_lineages=[])
    assignments = tuple(GapResponsibility(gap["gap_id"], "reviewer", "Investigate the fixed unresolved gap")
                        for gap in report_gaps(report))
    return report, CompletionOwnershipProof("completion", snapshot_digest(report), "revision",
                                            snapshot_digest("revision"), assignments)


def test_refinement_preserves_every_fact_and_blocker_except_unassigned_ownership():
    original, proof = original_and_proof()
    saved = deepcopy(original)
    report = assess_owned_completion(original, proof)
    assert original == saved and report["schema"] == "nasus.image-build-completion.v3"
    assert report["ownership"]["revision_hash"] == proof.revision_hash
    assert report["ownership"]["assignment_count"] == len(proof.assignments)
    assert report["blockers"] == [code for code in original["blockers"] if code != "gap_ownership_unassigned"]
    assert {"full_plan_budget_unverified", "critical_conflicts_unverified"} <= set(report["blockers"])
    assert all(gap["owner_actor_id"] == "reviewer" and gap["resolution_status"] == "unresolved"
               and gap["ownership_status"] == "confirmed" for gap in report["gaps"])
    for key in set(original) - {"schema", "gaps", "blockers"}:
        assert report[key] == original[key]
    assert snapshot_digest(report) == snapshot_digest(assess_owned_completion(original, proof))


@pytest.mark.parametrize("damage", ["missing", "duplicate", "foreign", "wrong_hash", "v1", "ready", "authority"])
def test_refinement_cannot_omit_invent_or_resolve_a_gap(damage):
    original, proof = original_and_proof()
    if damage == "missing":
        proof = replace(proof, assignments=proof.assignments[:-1])
    elif damage == "duplicate":
        proof = replace(proof, assignments=proof.assignments + proof.assignments[:1])
    elif damage == "foreign":
        proof = replace(proof, assignments=(GapResponsibility("gap_" + "0" * 64, "other", "foreign"), *proof.assignments[1:]))
    elif damage == "wrong_hash":
        proof = replace(proof, completion_report_hash=snapshot_digest("other"))
    else:
        original["schema" if damage == "v1" else "state" if damage == "ready" else "goal_completed"] = (
            "nasus.image-build-completion.v1" if damage == "v1" else "ready" if damage == "ready" else True)
        proof = replace(proof, completion_report_hash=snapshot_digest(original))
    with pytest.raises(BuildPlanIntegrityError):
        assess_owned_completion(original, proof)


def test_refinement_cannot_create_readiness_by_removing_the_only_blocker():
    original, proof = original_and_proof()
    original["blockers"] = ["gap_ownership_unassigned"]
    proof = replace(proof, completion_report_hash=snapshot_digest(original))
    with pytest.raises(BuildPlanIntegrityError, match="readiness"):
        assess_owned_completion(original, proof)


def test_owned_report_has_a_complete_nontruncating_byte_bound():
    original, proof = original_and_proof()
    original["padding"] = "x" * 65536
    proof = replace(proof, completion_report_hash=snapshot_digest(original))
    with pytest.raises(BuildPlanIntegrityError, match="64 KiB"):
        assess_owned_completion(original, proof)


@pytest.mark.parametrize("changes", [{"analysis_policy": None}, {"ownership_pin": {"latest": True}},
    {"analyses": [{"source_revision_id": "source", "analysis_id": "analysis", "report_hash": snapshot_digest("analysis")}]}])
def test_owned_input_requires_explicit_exact_pins_and_committed_build(changes):
    _, proof = original_and_proof()
    goal = paused_goal()
    pin = CompletionOwnershipPin(**{key: getattr(proof, key) for key in CompletionOwnershipPin.model_fields})
    body = dict(project_id=goal.project_id, investigation_revision_id="investigation",
                investigation_revision_hash=snapshot_digest("investigation"), expected_goal=goal.model_dump(mode="json"),
                analysis_policy="committed_build", ownership_pin=pin.model_dump())
    with pytest.raises(ValidationError):
        BuildCompletionInput(**{**body, **changes})


def test_old_request_hash_keeps_optional_ownership_absent():
    goal = paused_goal()
    body = dict(project_id=goal.project_id, investigation_revision_id="investigation",
                investigation_revision_hash=snapshot_digest("investigation"), expected_goal=goal.model_dump(mode="json"))
    request = BuildCompletionInput(**body)
    assert "ownership_pin" not in request.model_dump(mode="json", exclude_none=True)
