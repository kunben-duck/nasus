from __future__ import annotations

from dataclasses import dataclass

from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from ...domain.system_image.semantic_applicability import (
    SemanticApplicabilityAssessment, SemanticEndpointIdentity, assess_semantic_decision,
)


@dataclass(frozen=True)
class SemanticDecisionApplicability:
    project_id: str
    image_revision_id: str
    image_artifact_hash: str
    source_image_revision_id: str
    source_image_artifact_hash: str
    source_decision_id: str
    head_decision_id: str
    head_decision_digest: str
    assertion_id: str
    assertion_digest: str
    claim_id: str
    decision: str
    predicate: str
    original_subject: SemanticEndpointIdentity
    original_target: SemanticEndpointIdentity
    subject: SemanticEndpointIdentity
    target: SemanticEndpointIdentity
    assessment: SemanticApplicabilityAssessment
    history_scope: str = "pinned_claim_head_not_global_latest"
    publication: str = "not_in_image_membership"


class SemanticApplicabilityApplicationService:
    def __init__(self, images, reviews):
        self.images, self.reviews = images, reviews

    def read(self, project_id, image_revision_id, expected_image_hash, source_decision_id,
             subject_object_id, target_object_id, *, through_decision_id=None):
        scope = self.images.authorization.scope(project_id)
        selected = self.reviews.repository.selected(project_id, (source_decision_id,))
        if len(selected) != 1:
            raise KeyError("semantic decision not found")
        seed = selected[0]
        if seed.decision.decision_id != source_decision_id or seed.assertion.project_id != project_id:
            raise ImageRevisionIntegrityError("semantic applicability decision scope mismatch")
        # Verify the original evaluation and source ACL before looking up its
        # history; possessing a decision handle does not authorize source access.
        self._verified_assertion(project_id, seed.assertion)
        history = self.reviews.repository.history(project_id, seed.claim_id, through_decision_id)
        if not history or seed.decision not in history:
            raise ValueError("semantic applicability head precedes the selected decision")
        head = history[-1]
        selected_head = self.reviews.repository.selected(project_id, (head.decision_id,))
        if len(selected_head) != 1 or selected_head[0].decision != head or selected_head[0].claim_id != seed.claim_id:
            raise ImageRevisionIntegrityError("semantic applicability history mismatch")
        assertion = selected_head[0].assertion
        if assertion != seed.assertion:
            self._verified_assertion(project_id, assertion)
        old_header, old_image = self.images.frozen_snapshot(project_id, assertion.image_revision_id)
        header, image = self.images.frozen_snapshot(project_id, image_revision_id)
        if old_header.artifact_hash != assertion.image_artifact_hash or header.artifact_hash != expected_image_hash:
            raise ImageRevisionIntegrityError("semantic applicability image pins changed")
        original_subject = self._endpoint(project_id, old_header.image_revision_id, old_image, assertion.subject_object_id)
        original_target = self._endpoint(project_id, old_header.image_revision_id, old_image, assertion.object_id)
        if (original_subject.revision_id, original_target.revision_id) != (assertion.subject_revision_id, assertion.object_revision_id):
            raise ImageRevisionIntegrityError("semantic applicability original endpoints changed")
        subject = self._endpoint(project_id, image_revision_id, image, subject_object_id)
        target = self._endpoint(project_id, image_revision_id, image, target_object_id)
        assessment = assess_semantic_decision(head.decision, original_subject, original_target, subject, target)
        result = SemanticDecisionApplicability(project_id, image_revision_id, header.artifact_hash,
            old_header.image_revision_id, old_header.artifact_hash, source_decision_id, head.decision_id, head.digest,
            assertion.assertion_id, assertion.digest, assertion.claim_id, head.decision, assertion.predicate,
            original_subject, original_target, subject, target, assessment)
        self.images.authorization.require_current(scope)
        return result

    def _verified_assertion(self, project_id, assertion):
        actual = self.reviews.assertion(project_id, assertion.evaluation_id, assertion.subject_object_id)
        if actual != assertion:
            raise ImageRevisionIntegrityError("semantic applicability source assertion no longer verifies")

    def _endpoint(self, project_id, image_revision_id, image, object_id):
        member = next((item for item in image["members"] if item["object_id"] == object_id), None)
        if not member or member["kind"] not in {"code_entity", "source_document"}:
            raise KeyError("semantic endpoint is not in the selected image")
        bindings = {item["binding_id"] for item in image["source_members"]
                    if item["source_revision_id"] == member["source_revision_id"]}
        if len(bindings) != 1:
            raise ImageRevisionIntegrityError("semantic endpoint source binding is ambiguous")
        binding_id = next(iter(bindings))
        if member["kind"] == "code_entity":
            return SemanticEndpointIdentity(object_id, binding_id, member["entity_id"], member["entity_revision_id"],
                member["source_revision_id"], "code_entity", "registered_symbol")
        page = self.images.read_document(project_id, image_revision_id, object_id, limit=1)
        doc, projection = page["document"], page["projection"]
        if (doc["binding_id"] != binding_id or doc["document_revision_id"] != member["document_revision_id"]
                or doc["source_revision_id"] != member["source_revision_id"]):
            raise ImageRevisionIntegrityError("semantic applicability document scope mismatch")
        return SemanticEndpointIdentity(object_id, binding_id, doc["entity_id"], member["document_revision_id"],
            member["source_revision_id"], projection["kind"], projection["identity_status"])
