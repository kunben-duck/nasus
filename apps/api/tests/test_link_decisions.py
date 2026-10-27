from dataclasses import replace
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from apps.api.app.domain.system_image.link_decisions import LinkDecision, StaleLinkDecision, require_expected_decision


def decision():
    return LinkDecision("d1", "p", "proposal", "assertion", "image", "proposal-digest", "assertion-digest",
        "evidence-digest", "reject", "reviewer", "The reference is obsolete", "now", "invocation", None, 1)


def test_review_chain_requires_exact_previous_decision_and_keeps_negative_fact():
    original = decision()
    require_expected_decision(None, None)
    require_expected_decision(original, "d1")
    with pytest.raises(StaleLinkDecision):
        require_expected_decision(original, None)
    correction = replace(original, decision_id="d2", previous_decision_id="d1", sequence=2, decision="accept")
    assert original.decision == "reject" and correction.digest != original.digest


@pytest.mark.parametrize("change", [{"decision": "approved_coverage"}, {"reason": "  "}, {"reason": "x" * 2001},
    {"sequence": 2}, {"sequence": True}, {"sequence": 1001}, {"previous_decision_id": "d0"},
    {"policy_revision": "other"}, {"applicability": "all_versions"}, {"reviewer_actor": ""}])
def test_invalid_review_policy_or_chain_is_rejected(change):
    with pytest.raises(ValueError):
        replace(decision(), **change)


def test_application_rejects_a_repository_receipt_for_a_different_review():
    from apps.api.app.application.system_image.link_decisions import LinkDecisionApplicationService, LinkReviewInput
    from apps.api.app.application.system_image.reference_links import StoredReferenceProposal
    from apps.api.app.domain.system_image.reference_links import ReferenceAssertion, ReferenceProposal
    from apps.api.app.domain.system_image.link_decisions import assertion_evidence_digest, LINK_REVIEW_POLICY
    from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
    from apps.api.app.domain.system_image.source_snapshots import snapshot_digest

    edge = ReferenceAssertion("case", "case-rev", "req", "req-rev", "US-1", ("e1",), ("e2",))
    candidate = ReferenceProposal("p", "image", "image-hash", (edge,), (), 2)
    saved = StoredReferenceProposal("proposal", candidate.digest, "now", candidate, ("assertion",))
    scope = SimpleNamespace(actor_id="reviewer", effective_project_role="qa_lead")
    references = SimpleNamespace(authorization=SimpleNamespace(scope=lambda _: scope, require_current=lambda _: None),
        read=lambda *a, **kw: None, repository=SimpleNamespace(get=lambda *a: saved))
    request = LinkReviewInput(project_id="p", proposal_id="proposal", assertion_id="assertion", proposal_digest=candidate.digest,
        evidence_digest=assertion_evidence_digest(edge), policy_revision=LINK_REVIEW_POLICY, expected_previous_decision_id=None,
        decision="reject", reason="Stale reference")
    valid = replace(decision(), proposal_digest=candidate.digest, assertion_digest=snapshot_digest(asdict(edge)),
        evidence_digest=assertion_evidence_digest(edge), reason=request.reason)
    for bad in (replace(valid, reviewer_actor="other"), replace(valid, decision="accept"), replace(valid, image_revision_id="other")):
        service = LinkDecisionApplicationService(references, SimpleNamespace(record=lambda *a, **kw: bad))
        with pytest.raises(ImageRevisionIntegrityError):
            service.review(request, invocation_id="invocation", recorded_at="now")


def test_malformed_saved_payload_is_an_integrity_failure_not_a_client_validation_error():
    from apps.api.app.infrastructure.persistence.link_decision_repository import LinkDecisionRepository
    from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
    with pytest.raises(ImageRevisionIntegrityError):
        LinkDecisionRepository._read(SimpleNamespace(payload={"decision": "unknown"}))


def test_long_unicode_reasons_remain_fully_readable_through_byte_bounded_pages():
    import json
    from apps.api.app.application.system_image.link_decisions import LinkDecisionApplicationService
    from apps.api.app.domain.system_image.reference_links import ReferenceAssertion
    from apps.api.app.domain.system_image.link_decisions import assertion_evidence_digest
    from apps.api.app.domain.system_image.source_snapshots import snapshot_digest

    edge = ReferenceAssertion("case", "case-rev", "req", "req-rev", "US-1", ("e1",), ("e2",))
    history = tuple(replace(decision(), decision_id=f"d{i}", sequence=i,
        previous_decision_id=f"d{i - 1}" if i > 1 else None, reason="审" * 2000,
        assertion_digest=snapshot_digest(asdict(edge)), evidence_digest=assertion_evidence_digest(edge)) for i in range(1, 21))
    references = SimpleNamespace(authorization=SimpleNamespace(scope=lambda _: None, require_current=lambda _: None))
    service = LinkDecisionApplicationService(references, SimpleNamespace(history=lambda *args: history))
    service._assertion = lambda *args: (SimpleNamespace(digest="proposal-digest", proposal=SimpleNamespace(image_revision_id="image")), edge)
    first = service.read("p", "proposal", "assertion")
    assert 0 < first.next_offset < 20 and first.total == 20
    pages = [first]
    while pages[-1].next_offset is not None:
        offset = pages[-1].next_offset
        page = service.read("p", "proposal", "assertion", offset=offset)
        assert page.next_offset is None or page.next_offset > offset
        pages.append(page)
    items = tuple(item for page in pages for item in page.items)
    assert items == history and all(len(item.reason) == 2000 for item in items)
    assert all(len(json.dumps(asdict(page), ensure_ascii=False).encode()) <= 65536 for page in pages)
