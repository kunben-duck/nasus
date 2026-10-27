from dataclasses import asdict, replace
import json

import pytest

from apps.api.app.domain.system_image.investigation import InvestigationEvidence, decode_investigation, propose_investigation
from apps.api.app.domain.system_image.source_snapshots import SourceManifestMember, snapshot_digest
from apps.api.tests.test_build_plan import plan, manifest


def artifact(proposal, *, documents=0, missing=0, legacy=0):
    return {"project_id": proposal.intent.project_id, "manifest_id": proposal.intent.source_manifest_id,
        "manifest_hash": proposal.intent.source_manifest_hash,
        "members": [{"object_id": f"code-{i}", "kind": "code_entity", "source_revision_id": "revision",
                     "evidence_ids": [] if i < missing else [f"evidence-{i}"]} for i in range(12)]
        + [{"object_id": f"doc-{i}", "kind": "source_document", "source_revision_id": "doc-revision", "evidence_ids": [f"doc-evidence-{i}"]}
           for i in range(documents)]
        + [{"object_id": f"legacy-{i}", "kind": "legacy_observation", "evidence_ids": []} for i in range(legacy)]}


def test_code_only_evidence_revision_proposes_fixed_reads_not_approved_coverage():
    proposal = plan()
    payload = artifact(proposal)
    evidence = (InvestigationEvidence("code-0", "evidence-0", "revision", snapshot_digest("verified span")),)
    review = propose_investigation(proposal, "image", payload, evidence)
    assert review.state == "investigation_ready" and not review.publication_allowed
    assert review.inventory["verified_evidence_sample"] == 1
    assert review.readiness["structure"]["state"] == "membership_verified_not_coverage"
    assert all(item["coverage"] is None for item in review.readiness.values())
    assert {gap.code for gap in review.gaps} >= {"evidence_inspection_partial", "us_doc_unavailable",
        "test_asset_unavailable", "business_oracle_authority_unresolved", "runtime_evidence_unresolved"}
    assert all(task.tool_id.startswith("query.system_image.revisions.") and task.max_model_calls == 0
               and task.authorization_state == "not_granted" and task.input_payload["image_revision_id"] == "image" for task in review.work_items)
    assert decode_investigation(json.loads(json.dumps(asdict(review)))) == review


def test_three_no_new_evidence_iterations_pause_and_new_artifact_resets_counter():
    proposal = plan()
    payload = artifact(proposal)
    review = propose_investigation(proposal, "image", payload, ())
    for count in range(1, 4):
        review = propose_investigation(proposal, "image", payload, (), previous=review)
        assert review.no_progress_rounds == count
    assert review.state == "paused_no_progress" and review.work_items == ()
    changed = {**payload, "additional_observation": "a separately frozen fact"}
    reset = propose_investigation(proposal, "image-2", changed, (), previous=review)
    assert reset.no_progress_rounds == 0 and reset.consumed_review_calls == 5


def test_document_gaps_choose_bounded_field_reads_and_keep_approval_unresolved():
    proposal = plan(manifest(SourceManifestMember("code", "code", "revision", "captured"),
        SourceManifestMember("doc", "us_doc", "doc-revision", "captured")))
    review = propose_investigation(proposal, "image", artifact(proposal, documents=7, missing=1, legacy=2), ())
    assert len([task for task in review.work_items if task.tool_id.endswith(".document")]) == 4
    assert {gap.code for gap in review.gaps} >= {"document_semantics_unreviewed", "document_investigation_truncated",
        "structural_evidence_incomplete", "business_oracle_authority_unresolved"}
    assert "us_doc_unavailable" not in {gap.code for gap in review.gaps}
    assert review.readiness["structure"]["state"] == "evidence_gaps"


def test_plan_proposal_ceiling_never_expands_and_exhaustion_removes_tasks():
    original = plan()
    proposal = replace(original, intent=replace(original.intent, budget=replace(original.intent.budget, max_tool_calls=2)))
    review = propose_investigation(proposal, "image", artifact(proposal, documents=4), ())
    assert len(review.work_items) == 1 and "investigation_budget_insufficient" in {gap.code for gap in review.gaps}
    next_review = propose_investigation(proposal, "image", artifact(proposal, documents=4), (), previous=review)
    assert next_review.state == "paused_budget" and next_review.work_items == ()
    assert next_review.consumed_review_calls == 2


@pytest.mark.parametrize("change", [{"manifest_id": "outside"}, {"project_id": "outside"}, {"manifest_hash": snapshot_digest("outside")}])
def test_investigation_cannot_change_fixed_input_scope(change):
    proposal = plan()
    with pytest.raises(ValueError):
        propose_investigation(proposal, "image", {**artifact(proposal), **change}, ())


def test_evidence_cannot_be_invented_or_borrowed_from_another_object():
    proposal = plan()
    for pin in (InvestigationEvidence("outside", "evidence-0", "revision", snapshot_digest("x")),
                InvestigationEvidence("code-0", "evidence-1", "revision", snapshot_digest("x")),
                InvestigationEvidence("code-0", "evidence-0", "other-revision", snapshot_digest("x"))):
        with pytest.raises(ValueError):
            propose_investigation(proposal, "image", artifact(proposal), (pin,))


def test_reordering_subsetting_or_alternating_old_evidence_is_not_progress():
    proposal = plan()
    payload = artifact(proposal)
    one = InvestigationEvidence("code-0", "evidence-0", "revision", snapshot_digest("span-0"))
    two = InvestigationEvidence("code-1", "evidence-1", "revision", snapshot_digest("span-1"))
    first = propose_investigation(proposal, "image", payload, (one, two))
    reordered = propose_investigation(proposal, "image", payload, (two, one), previous=first)
    assert reordered.evidence_signature == first.evidence_signature and reordered.no_progress_rounds == 1
    subset = propose_investigation(proposal, "image", payload, (one,), previous=reordered)
    assert subset.no_progress_rounds == 2
    old = propose_investigation(proposal, "image", payload, (two,), previous=subset)
    assert old.state == "paused_no_progress" and old.observed_evidence_keys == first.observed_evidence_keys


def test_deterministic_investigation_does_not_call_generic_model_replanner():
    import asyncio
    from types import SimpleNamespace
    from apps.api.app.application.agent.graph import LocalAgentGraphRuntime

    class ForbiddenReplanner:
        async def replan(self, request):
            pytest.fail("Deterministic inspection does not grant model egress.")

    runtime = LocalAgentGraphRuntime(None, None, None, replanner=ForbiddenReplanner())
    goal = SimpleNamespace(status="running", steps=[SimpleNamespace(selected_tool_id="system_image.build.investigate")])
    asyncio.run(runtime._replan_after_observation(goal, 0, "Fixed evidence inspected"))


def three_source_plan():
    return plan(manifest(SourceManifestMember("code", "code", "revision", "captured"),
        SourceManifestMember("doc", "us_doc", "doc-revision", "captured"),
        SourceManifestMember("test", "test_asset", "test-revision", "captured")))


def test_v2_proposes_explicit_references_on_fixed_three_source_image_without_coverage():
    proposal = three_source_plan()
    payload = artifact(proposal, documents=2)
    legacy = propose_investigation(proposal, "image", payload, ())
    review = propose_investigation(proposal, "image", payload, (),
        policy_version="nasus.image-investigation-revision.v2")
    assert review.policy_version.endswith(".v2") and review.digest != legacy.digest
    task = review.work_items[-1]
    assert task.tool_id == "system_image.links.propose_references"
    assert task.input_payload == {"project_id": proposal.intent.project_id, "image_revision_id": "image"}
    assert task.max_model_calls == 0 and task.max_attempts == 1 and task.authorization_state == "not_granted"
    assert "explicit_reference_candidates_unreviewed" in {gap.code for gap in review.gaps}
    assert not review.publication_allowed and all(item["coverage"] is None for item in review.readiness.values())
    assert decode_investigation(json.loads(json.dumps(asdict(review)))) == review
    assert not any(task.tool_id == "system_image.links.propose_references" for task in legacy.work_items)
    assert decode_investigation(json.loads(json.dumps(asdict(legacy)))) == legacy


def test_v2_does_not_invent_reference_work_for_missing_optional_sources_or_projections():
    for proposal, documents in ((plan(), 0), (plan(), 2), (three_source_plan(), 0)):
        review = propose_investigation(proposal, "image", artifact(proposal, documents=documents), (),
            policy_version="nasus.image-investigation-revision.v2")
        assert not any(task.tool_id == "system_image.links.propose_references" for task in review.work_items)
        if proposal == three_source_plan():
            assert "reference_source_projection_missing" in {gap.code for gap in review.gaps}


def test_policy_cannot_silently_upgrade_a_previous_investigation_or_accept_unknown_versions():
    proposal = three_source_plan()
    payload = artifact(proposal, documents=2)
    old = propose_investigation(proposal, "image", payload, ())
    with pytest.raises(ValueError, match="policy"):
        propose_investigation(proposal, "image", payload, (), previous=old,
            policy_version="nasus.image-investigation-revision.v2")
    with pytest.raises(ValueError, match="policy"):
        propose_investigation(proposal, "image", payload, (), policy_version="unknown")
