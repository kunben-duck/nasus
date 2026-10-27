from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from apps.api.app.application.agent.observation_receipts import observation_receipt_fingerprint
from apps.api.app.application.platform.approval_verifier import ToolApprovalVerifierApplicationService
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.quality_loop.quality_models import ApprovalDetail
from apps.api.app.application.system_image.publications import (PublicationPreviewReceipt, PublicationTarget, PublicationHeadReceipt,
    PublicationHeadInput, PublicationHeadPin, RollbackTarget, RollbackReviewInput, target_of)
from apps.api.app.domain.system_image.publication import PUBLICATION_POLICY, ROLLBACK_POLICY, PublicationChanged, require_live_approval
from apps.api.app.infrastructure.platform.approval_verification import ProjectedToolApprovalVerificationState, ToolApprovalVerificationFacts, SQLAlchemyToolApprovalVerificationState


TARGET = dict(project_id="p", image_revision_id="image", image_artifact_hash="sha256:" + "a" * 64,
    target_baseline_id="baseline", expected_head_id=None, policy_revision=PUBLICATION_POLICY)


@pytest.mark.parametrize("age,valid", [(0, True), (1800, True), (1801, False), (-1, False)])
def test_publication_approval_ttl_is_bounded(age, valid):
    now = datetime(2026, 9, 19, tzinfo=timezone.utc)
    approval = dict(claim_digest="claim", review_id="review", decision="approve", policy_revision=PUBLICATION_POLICY,
        recorded_at=(now - timedelta(seconds=age)).isoformat())
    if valid:
        require_live_approval(approval, claim="claim", previous_review_id="review", now=now)
    else:
        with pytest.raises(PublicationChanged):
            require_live_approval(approval, claim="claim", previous_review_id="review", now=now)


@pytest.mark.parametrize("change", [{"decision": "reject"}, {"claim_digest": "another"}, {"review_id": "new"}, {"policy_revision": "other"}])
def test_publication_approval_is_exact_not_generic(change):
    approval = dict(claim_digest="claim", review_id="review", decision="approve", policy_revision=PUBLICATION_POLICY,
        recorded_at=datetime.now(timezone.utc).isoformat())
    with pytest.raises(PublicationChanged):
        require_live_approval({**approval, **change}, claim="claim", previous_review_id="review")


def test_publication_requires_explicit_empty_head_and_observation_binds_entire_receipt():
    with pytest.raises(ValidationError):
        PublicationTarget.model_validate({k: v for k, v in TARGET.items() if k != "expected_head_id"})
    receipt = PublicationPreviewReceipt(request=PublicationTarget(**TARGET), preview_digest="sha256:" + "b" * 64,
        review_id=None, review_decision=None)
    result = ToolResult(invocation_id="tool", status="completed", summary="Preview", image_publication=receipt)
    before = observation_receipt_fingerprint(result)
    assert before
    after = result.model_copy(update={"image_publication": receipt.model_copy(update={"review_id": "review", "review_decision": "approve"})})
    assert observation_receipt_fingerprint(after) != before
    assert observation_receipt_fingerprint(result.model_copy(update={"status": "failed"})) is None


def test_head_receipt_fingerprint_binds_head_identity_and_sequence():
    request = PublicationHeadInput(project_id="p", target_baseline_id="baseline")
    receipt = PublicationHeadReceipt(request=request, head=None)
    result = ToolResult(invocation_id="tool", status="completed", summary="Head", image_publication_head=receipt)
    empty = observation_receipt_fingerprint(result)
    head = PublicationHeadPin(publication_id="publication", image_revision_id="image",
        image_artifact_hash=TARGET["image_artifact_hash"], sequence=1)
    changed = result.model_copy(update={"image_publication_head": receipt.model_copy(update={"head": head})})
    assert empty and observation_receipt_fingerprint(changed) != empty


def test_rollback_target_and_receipt_cannot_be_downgraded_to_normal_publication():
    target = {**TARGET, "expected_head_id": "current", "rollback_publication_id": "historical", "policy_revision": ROLLBACK_POLICY}
    rollback = RollbackTarget(**target)
    assert target_of(rollback) == rollback
    with pytest.raises(ValidationError): PublicationTarget(**target)
    with pytest.raises(ValidationError): RollbackTarget(**{**target, "expected_head_id": None})
    with pytest.raises(ValidationError): RollbackReviewInput(**target, expected_preview_digest="sha256:" + "b" * 64,
        expected_review_id=None, decision="approve", reason=" ")
    receipt = PublicationPreviewReceipt(request=rollback, preview_digest="sha256:" + "b" * 64, review_id=None, review_decision=None)
    assert isinstance(PublicationPreviewReceipt.model_validate(receipt.model_dump()).request, RollbackTarget)


@pytest.mark.parametrize("adapter", ["projected", "committed"])
def test_both_approval_adapters_restrict_publication_purpose(adapter):
    approval = ApprovalDetail(id="review", title="Review", status="approved", summary="Only image publication",
        policy_reason=PUBLICATION_POLICY, recommended_resolution="Publish exact image")
    if adapter == "projected":
        state = ProjectedToolApprovalVerificationState(ToolApprovalVerificationFacts(
            conversations={}, approvals={"p": [approval]}, approval_details={"review": approval}))
    else:
        class Repository:
            def get_approval_detail(self, project_id, approval_id):
                return approval if (project_id, approval_id) == ("p", "review") else None
        state = SQLAlchemyToolApprovalVerificationState(None, Repository())
    verifier = ToolApprovalVerifierApplicationService(state)
    invocation = ToolInvocation(id="tool", tool_id="release.decision.submit", status="pending", summary="Test",
        input_payload={"project_id": "p", "approval_id": "review"})
    assert verifier.allows_tool_invocation(invocation)[0] is False
    invocation.tool_id = "baseline.promote"
    assert verifier.allows_tool_invocation(invocation)[0] is False
    invocation.input_payload = {**TARGET, "approval_id": "review", "expected_preview_digest": "sha256:" + "b" * 64}
    assert verifier.allows_tool_invocation(invocation)[0] is True
