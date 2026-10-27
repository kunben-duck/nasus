from dataclasses import replace

import pytest

from apps.api.app.domain.system_image.semantic_applicability import SemanticEndpointIdentity, assess_semantic_decision


SUBJECT = SemanticEndpointIdentity("code", "repo", "entity", "revision", "source", "code_entity", "registered_symbol")
TARGET = SemanticEndpointIdentity("ac", "requirements", "criterion", "ac-revision", "document", "acceptance_criterion", "explicit_id")


@pytest.mark.parametrize("decision", ["accept", "reject", "defer"])
def test_same_revisions_preserve_negative_but_never_transfer_approval(decision):
    value = assess_semantic_decision(decision, SUBJECT, TARGET, replace(SUBJECT, object_id="new-code-handle"), TARGET)
    assert value.status == ("rejected_same_revisions" if decision == "reject" else "same_revisions_review_required")
    assert not value.approval_transferred


@pytest.mark.parametrize("decision", ["accept", "reject", "defer"])
@pytest.mark.parametrize("side", ["subject", "target"])
@pytest.mark.parametrize("field", ["revision_id", "source_revision_id"])
def test_changes_require_revalidation_even_when_registry_identity_is_preserved(decision, side, field):
    subject = replace(SUBJECT, **{field: "changed"}) if side == "subject" else SUBJECT
    target = replace(TARGET, **{field: "changed"}) if side == "target" else TARGET
    result = assess_semantic_decision(decision, SUBJECT, TARGET, subject, target)
    assert result.status == "stale_requires_review" and result.candidate_action == "revalidate_before_review"
    assert not result.approval_transferred


@pytest.mark.parametrize("field", ["binding_id", "entity_id"])
def test_same_labels_or_object_handle_do_not_override_registry_identity(field):
    assert assess_semantic_decision("reject", SUBJECT, TARGET, replace(SUBJECT, **{field: "other"}), TARGET).status == "different_endpoints"


@pytest.mark.parametrize("basis", ["ambiguous", "source_occurrence"])
def test_unstable_document_identity_never_implies_cross_revision_lineage(basis):
    target = replace(TARGET, identity_basis=basis)
    assert assess_semantic_decision("reject", SUBJECT, target, SUBJECT, replace(target, revision_id="next")).status == "identity_unresolved"
    assert assess_semantic_decision("reject", SUBJECT, target, SUBJECT, target).status == "rejected_same_revisions"


@pytest.mark.parametrize("changes", [{"entity_id": ""}, {"binding_id": 3}, {"kind": "requirement"}, {"identity_basis": "title_match"}])
def test_invalid_identity_is_rejected(changes):
    with pytest.raises(ValueError):
        replace(TARGET, **changes)
