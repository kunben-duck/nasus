from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from apps.api.app.domain.system_image.image_revision import verify_image_artifact, ImageRevisionIntegrityError
from apps.api.app.domain.system_image.image_membership import build_reviewed_artifact
from apps.api.app.domain.system_image.semantic_membership import (
    ImageSemanticMember, build_semantic_artifact, semantic_membership_digest, SEMANTIC_IMAGE_POLICY,
)
from apps.api.app.domain.system_image.semantic_review import SemanticAssertion, SemanticDecision
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.tests.test_image_membership import reviewed


def frozen():
    _, parent, summary, reference = reviewed()
    digest = snapshot_digest({})
    assertion = SemanticAssertion(parent["project_id"], "child", summary.artifact_hash, "evaluation", digest, digest,
        "test", "test-v1", "requirement", "requirement-v1", "asserts", "unknown", ("test-evidence",), ("requirement-evidence",), digest, None)
    decision = SemanticDecision("semantic-decision", assertion.project_id, assertion.claim_id, assertion.assertion_id, assertion.digest,
        assertion.evidence_digest, assertion.evaluation_id, assertion.image_revision_id, "defer", "No independent oracle", "reviewer", "now", "invocation", None, 1)
    member = ImageSemanticMember(assertion, decision)
    payload = build_semantic_artifact(parent, "child", summary.artifact_hash, (member,))
    header = replace(summary, image_revision_id="semantic-child", parent_revision_id="child", parent_artifact_hash=summary.artifact_hash,
        policy_version=SEMANTIC_IMAGE_POLICY, assertion_count=2, artifact_hash=snapshot_digest(payload),
        membership_hash=semantic_membership_digest(payload["members"], payload["assertion_members"], payload["semantic_assertion_members"]))
    return payload, header, member, reference


def test_semantic_and_reference_freezes_preserve_each_other_and_do_not_publish():
    payload, header, member, reference = frozen()
    verify_image_artifact(payload, header)
    original = deepcopy(payload)
    updated = build_reviewed_artifact(payload, header.image_revision_id, header.artifact_hash,
        (replace(reference, decision_id="new-reference-decision", decision="accept"),))
    assert updated["schema"] == SEMANTIC_IMAGE_POLICY
    assert updated["semantic_assertion_members"] == original["semantic_assertion_members"]
    updated = build_semantic_artifact(payload, header.image_revision_id, header.artifact_hash,
        (replace(member, decision=replace(member.decision, decision_id="rejected", decision="reject", previous_decision_id=member.decision.decision_id, sequence=2)),))
    assert updated["assertion_members"] == payload["assertion_members"]
    assert payload == original and payload["publication"] == "blocked_pending_revision_governance"
    assert updated["semantic_assertion_members"][0]["assertion"]["authority_status"] == "pending_confirmation"


@pytest.mark.parametrize("change", ["unknown_accept", "scope", "revision", "evidence", "claim", "assertion_digest", "empty", "duplicate", "extra", "promotion", "count"])
def test_semantic_artifact_rejects_tampering_even_with_rehashed_transport(change):
    payload, header, _, _ = frozen()
    m = payload["semantic_assertion_members"][0]
    if change == "unknown_accept": m["decision"]["decision"] = "accept"
    elif change == "scope": m["assertion"]["project_id"] = "other"
    elif change == "revision": m["assertion"]["subject_revision_id"] = "other"
    elif change == "evidence": m["assertion"]["object_evidence_ids"] = ["later"]
    elif change == "claim": m["decision"]["claim_id"] = "other"
    elif change == "assertion_digest": m["decision"]["assertion_digest"] = snapshot_digest({})
    elif change == "empty": payload["semantic_assertion_members"] = []
    elif change == "duplicate": payload["semantic_assertion_members"] *= 2
    elif change == "extra": m["approved"] = True
    elif change == "promotion": m["assertion"]["authority_status"] = "approved"
    else: header = replace(header, assertion_count=3)
    header = replace(header, artifact_hash=snapshot_digest(payload), membership_hash=semantic_membership_digest(
        payload["members"], payload["assertion_members"], payload["semantic_assertion_members"]))
    with pytest.raises(ImageRevisionIntegrityError):
        verify_image_artifact(payload, header)


def test_new_image_claim_cannot_bypass_existing_frozen_endpoint_review():
    payload, header, member, _ = frozen()
    assertion = replace(member.assertion, image_revision_id=header.image_revision_id, image_artifact_hash=header.artifact_hash)
    decision = replace(member.decision, decision_id="new-decision", image_revision_id=assertion.image_revision_id,
        assertion_id=assertion.assertion_id, assertion_digest=assertion.digest, claim_id=assertion.claim_id)
    with pytest.raises(ImageRevisionIntegrityError, match="endpoint collision"):
        build_semantic_artifact(payload, header.image_revision_id, header.artifact_hash, (ImageSemanticMember(assertion, decision),))
