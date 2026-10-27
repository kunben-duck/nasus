from dataclasses import replace

import pytest

from apps.api.app.domain.system_image.reference_links import (
    ReferenceDocument, ReferenceMention, propose_references, requirement_references,
)


def inputs():
    return (
        ReferenceDocument("requirement", "requirement@1", "source@1", "requirement", "US-17", "explicit_id",
                          ("req-whole", "req-ac"), ("req-whole",), ()),
        ReferenceDocument("case", "case@1", "tests@1", "test_case", "TC-9", "explicit_id",
                          ("case-whole", "case-reference"), ("case-whole",), (ReferenceMention("US-17", ("case-reference",)),)),
    )


def propose(documents):
    return propose_references("project", "image", "sha256:" + "1" * 64, tuple(documents))


def test_exact_reference_proposal_never_claims_coverage_or_approval():
    proposal = propose(inputs())
    assert proposal.digest == propose(tuple(reversed(inputs()))).digest
    assertion, = proposal.assertions
    assert (assertion.predicate, assertion.semantic_kind, assertion.status) == ("references", "observed", "proposed")
    assert assertion.subject_revision_id == "case@1"
    assert assertion.object_revision_id == "requirement@1"
    assert assertion.subject_evidence_ids == ("case-reference",)
    assert assertion.object_evidence_ids == ("req-whole",)
    assert proposal.gaps == ()
    changed = propose((replace(inputs()[0], document_revision_id="requirement@2"), inputs()[1]))
    assert changed.digest != proposal.digest and changed.assertions[0].status == "proposed"


@pytest.mark.parametrize("reason,documents", [
    ("target_not_in_selected_image", (inputs()[1],)),
    ("ambiguous_reference_target", (*inputs(), replace(inputs()[0], object_id="duplicate", document_revision_id="other"))),
    ("ambiguous_reference_target", (replace(inputs()[0], identity_status="ambiguous"), inputs()[1])),
    ("ambiguous_subject_identity", (inputs()[0], replace(inputs()[1], identity_status="ambiguous"))),
    ("target_evidence_missing", (replace(inputs()[0], identity_evidence_ids=()), inputs()[1])),
    ("self_reference", (replace(inputs()[0], mentions=(ReferenceMention("US-17", ("req-whole",)),)),)),
])
def test_uncertainty_is_a_gap_not_an_arbitrary_edge(reason, documents):
    result = propose(documents)
    assert not result.assertions and result.gaps[0].reason == reason


def test_repeated_mentions_merge_evidence_without_duplicate_assertions():
    req, case = inputs()
    result = propose((req, replace(case, mentions=(*case.mentions, ReferenceMention("US-17", ("case-whole",))))))
    assert len(result.assertions) == 1
    assert result.assertions[0].subject_evidence_ids == ("case-reference", "case-whole")
    with pytest.raises(ValueError, match="frozen field evidence"):
        propose((req, replace(case, mentions=(ReferenceMention("US-17", ("other",)),))))


def test_reference_matching_does_not_match_substrings_or_invent_requirements():
    assert requirement_references("US-17, req-2; 中文US-17；TC-4") == ("REQ-2", "US-17")
    assert requirement_references("XUS-17 prefix.US-17 prefix_US-17 US-170") == ("US-170",)
    assert propose((replace(inputs()[0], kind="test_case"), inputs()[1])).gaps[0].reason == "target_not_in_selected_image"


def test_reference_budget_and_unique_identity_are_enforced():
    with pytest.raises(ValueError, match="reference input"):
        propose((*inputs(), inputs()[0]))
    with pytest.raises(ValueError, match="budget"):
        propose((replace(inputs()[1], mentions=inputs()[1].mentions * 10001),))
