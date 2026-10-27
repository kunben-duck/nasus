from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from apps.api.app.domain.system_image.image_revision import build_image_artifact, verify_image_artifact, ImageRevisionIntegrityError
from apps.api.app.domain.system_image.image_membership import (
    ImageAssertionMember, REVIEWED_IMAGE_POLICY, build_reviewed_artifact, reviewed_membership_digest,
)
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.tests.test_image_revision import candidate, header


def reviewed():
    manifest, objects, relationships = candidate()
    for name in ("requirement", "test"):
        objects.append({"id": name, "name": name, "document_reference": {
            "document_revision_id": name + "-v1", "source_revision_id": "source-revision"}})
    parent, _ = build_image_artifact(manifest, "baseline", objects, relationships)
    for member in parent["members"]:
        if member["kind"] == "source_document":
            member["evidence_ids"] = [member["object_id"] + "-evidence"]
    digest = snapshot_digest({})
    member = ImageAssertionMember("assertion", "proposal", "parent", digest, digest, digest, "decision", digest, "reject",
        "test", "test-v1", "requirement", "requirement-v1", ("test-evidence",), ("requirement-evidence",))
    payload = build_reviewed_artifact(parent, "parent", snapshot_digest(parent), (member,))
    summary = replace(header(parent), image_revision_id="child", object_count=4, artifact_hash=snapshot_digest(payload),
        policy_version=REVIEWED_IMAGE_POLICY, parent_revision_id="parent", parent_artifact_hash=snapshot_digest(parent), assertion_count=1,
        membership_hash=reviewed_membership_digest(payload["members"], payload["assertion_members"]))
    return parent, payload, summary, member


def test_reviewed_snapshot_does_not_promote_references_or_change_parent():
    parent, payload, summary, member = reviewed()
    original = deepcopy(payload)
    verify_image_artifact(payload, summary)
    assert "assertion_members" not in parent
    updated = build_reviewed_artifact(payload, "child", summary.artifact_hash,
        (replace(member, decision_id="new-decision", decision="accept"),))
    assert payload == original and updated["assertion_members"][0]["decision"] == "accept"
    assert updated["publication"] == "blocked_pending_revision_governance"
    assert updated["assertion_members"][0]["predicate"] == "references"
    assert updated["objects"] == parent["objects"] and updated["relationships"] == parent["relationships"]


def test_new_proposal_cannot_bypass_a_negative_decision_with_duplicate_endpoints():
    _, payload, summary, member = reviewed()
    duplicate = replace(member, assertion_id="new-assertion", proposal_id="new-proposal", decision_id="another-decision", decision="accept")
    with pytest.raises(ImageRevisionIntegrityError, match="duplicate reference endpoints"):
        build_reviewed_artifact(payload, "child", summary.artifact_hash, (duplicate,))


@pytest.mark.parametrize("field,value", [
    ("subject_revision_id", "unfrozen"), ("object_revision_id", "unfrozen"),
    ("subject_evidence_ids", ("later-evidence",)), ("object_evidence_ids", ("foreign",)),
    ("subject_object_id", "code"), ("decision", "approve_coverage"), ("predicate", "asserts"),
    ("applicability", "all_versions"), ("decision_digest", "not-a-hash"),
])
def test_invalid_endpoints_evidence_and_semantic_promotion_are_rejected(field, value):
    parent, _, summary, member = reviewed()
    with pytest.raises((ValueError, ImageRevisionIntegrityError)):
        build_reviewed_artifact(parent, "parent", summary.parent_artifact_hash, (replace(member, **{field: value}),))


@pytest.mark.parametrize("change", ["missing", "duplicate", "wrong_parent", "self_parent", "count", "digest", "unknown_field"])
def test_full_assertion_membership_is_verified_even_with_matching_transport_hash(change):
    _, payload, summary, _ = reviewed()
    if change == "missing":
        payload["assertion_members"] = []
    elif change == "duplicate":
        payload["assertion_members"] *= 2
    elif change == "wrong_parent":
        payload["parent_revision_id"] = "another-parent"
    elif change == "self_parent":
        summary = replace(summary, parent_revision_id="child")
    elif change == "count":
        summary = replace(summary, assertion_count=2)
    elif change == "digest":
        payload["assertion_members"][0]["decision_digest"] = "bad"
    else:
        payload["assertion_members"][0]["approved_oracle"] = True
    summary = replace(summary, artifact_hash=snapshot_digest(payload),
        membership_hash=reviewed_membership_digest(payload["members"], payload["assertion_members"]))
    with pytest.raises(ImageRevisionIntegrityError):
        verify_image_artifact(payload, summary)
