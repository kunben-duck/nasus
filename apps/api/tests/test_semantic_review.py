import asyncio
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.semantic_review import SemanticReviewApplicationService, SemanticReviewInput
from apps.api.app.domain.system_image.semantic_review import SEMANTIC_REVIEW_POLICY, stored_semantic_assertion
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.infrastructure.persistence.semantic_review_repository import SemanticReviewRepository
from apps.api.tests.test_semantic_evaluations import service


def prepared_review(service):
    asyncio.run(service.application.evaluate(service.request, invocation_id="evaluation"))
    app = SemanticReviewApplicationService(service.application, service.application.images.authorization,
                                           SimpleNamespace(history=lambda *args: ()))
    return app, app.assertion("p", "evaluation", "subject")


def test_semantic_assertion_is_derived_from_fixed_evaluation_without_copying_source(service):
    app, assertion = prepared_review(service)
    assert assertion.can_accept and assertion.predicate == "asserts"
    assert assertion.status == "proposed" and assertion.authority_status == "pending_confirmation"
    assert "HTTP 400" not in str(asdict(assertion))
    assert stored_semantic_assertion(asdict(assertion)) == assertion
    other = replace(assertion, evaluation_id="second-evaluation", evaluation_artifact_hash="sha256:" + "b" * 64)
    assert other.assertion_id != assertion.assertion_id and other.claim_id == assertion.claim_id
    for fields in ({"subject_revision_id": "new"}, {"object_revision_id": "new"}, {"image_revision_id": "new"}):
        assert replace(assertion, **fields).claim_id != assertion.claim_id
    assert app.read("p", "evaluation", "subject")["publication"] == "not_in_image_membership"


@pytest.mark.parametrize("assessment", ["unknown", "contradicts", "unrelated"])
def test_review_cannot_upgrade_an_unsupported_model_claim(service, assessment):
    _, assertion = prepared_review(service)
    unsupported = replace(assertion, assessment=assessment)
    with pytest.raises(ValueError, match="grounded"):
        unsupported.require_decision("accept")
    unsupported.require_decision("reject")
    unsupported.require_decision("defer")
    with pytest.raises(ValueError):
        replace(assertion, oracle_digest=None).require_decision("accept")


def test_review_rejects_forged_scope_and_nonreviewer_before_persistence(service):
    app, assertion = prepared_review(service)
    request = SemanticReviewInput(project_id="p", evaluation_id="evaluation", subject_object_id="subject",
        assertion_id=assertion.assertion_id, assertion_digest=assertion.digest, evidence_digest=assertion.evidence_digest,
        expected_previous_decision_id=None, policy_revision=SEMANTIC_REVIEW_POLICY, decision="reject", reason="Independent reviewer reason")
    service.scope.effective_project_role = "tester"
    with pytest.raises(SourceAccessDenied):
        app.review(request, invocation_id="review", recorded_at="now")
    with pytest.raises(KeyError):
        app.read("p", "evaluation", "foreign-subject")


@pytest.mark.parametrize("payload", [{}, {"reason": None}, {"subject_evidence_ids": None}, {"evidence_digest": "invalid"}])
def test_malformed_persisted_reviews_fail_as_integrity_errors(payload):
    with pytest.raises(ImageRevisionIntegrityError):
        SemanticReviewRepository._assertion(SimpleNamespace(payload=payload))
    with pytest.raises(ImageRevisionIntegrityError):
        SemanticReviewRepository._decision(None, SimpleNamespace(payload=payload))


def test_semantic_review_page_rechecks_acl_and_bounds(service):
    app, assertion = prepared_review(service)
    for offset, limit in [(-1, 20), (0, 0), (0, 51), (True, 20), (1001, 1)]:
        with pytest.raises(ValueError):
            app.read("p", "evaluation", "subject", offset=offset, limit=limit)
    from apps.api.app.domain.system_image.semantic_review import SemanticDecision
    decision = SemanticDecision("d", "p", assertion.claim_id, assertion.assertion_id, assertion.digest, assertion.evidence_digest,
        "evaluation", assertion.image_revision_id, "defer", "Needs approved authority", "reviewer", "now", "invocation", None, 1)
    app.repository.history = lambda *args: (decision,)
    page = app.read("p", "evaluation", "subject")
    assert page["head"] == asdict(decision) and page["head_decision_id"] == "d"
    for fields in ({"reason": None}, {"reason": " "}, {"reviewer_actor": []}, {"sequence": True}, {"previous_decision_id": ""}):
        with pytest.raises(ValueError):
            replace(decision, **fields)
