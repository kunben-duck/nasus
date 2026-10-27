from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from ...domain.system_image.semantic_applicability import SemanticEndpointIdentity
from ...domain.system_image.source_snapshots import snapshot_digest


SEMANTIC_SCREENING_POLICY = "nasus.semantic-review-screening.v1"
MAX_MATCHED_REVIEW_HEADS = 64


class SemanticReviewHeadPort(Protocol):
    def matching_heads(self, project_id, predicate, subjects, target): ...


@dataclass(frozen=True)
class SemanticScreeningItem:
    subject_object_id: str
    head_decision_id: str
    head_decision_digest: str
    claim_id: str
    source_image_revision_id: str
    decision: str
    status: str
    candidate_action: str


@dataclass(frozen=True)
class SemanticScreeningSnapshot:
    project_id: str
    image_revision_id: str
    image_artifact_hash: str
    predicate: str
    subjects: tuple[SemanticEndpointIdentity, ...]
    target: SemanticEndpointIdentity
    items: tuple[SemanticScreeningItem, ...]
    policy_revision: str = SEMANTIC_SCREENING_POLICY

    @property
    def digest(self):
        return snapshot_digest(asdict(self))

    @property
    def head_pins(self):
        return tuple((item.subject_object_id, item.head_decision_id, item.head_decision_digest) for item in self.items)

    def require_eligible(self):
        if any(item.status in {"rejected_same_revisions", "identity_unresolved", "different_endpoints"} for item in self.items):
            raise ValueError("semantic review blocks model egress; review the original decision before retrying")


class SemanticScreeningApplicationService:
    def __init__(self, applicability, heads: SemanticReviewHeadPort):
        self.applicability, self.heads = applicability, heads

    def screen(self, request):
        images = self.applicability.images
        scope = images.authorization.scope(request.project_id)
        header, image = images.frozen_snapshot(request.project_id, request.image_revision_id)
        if header.artifact_hash != request.expected_image_hash:
            raise ImageRevisionIntegrityError("semantic screening image changed")
        target = self.applicability._endpoint(request.project_id, request.image_revision_id, image, request.target_object_id)
        subjects = tuple(self.applicability._endpoint(request.project_id, request.image_revision_id, image, ident)
                         for ident in sorted(request.subject_object_ids))
        if (not 1 <= len(subjects) <= 30 or len({s.identity_key for s in subjects}) != len(subjects)
                or target.kind not in {"acceptance_criterion", "business_rule"}
                or any(s.kind != ("code_entity" if request.relation == "implements" else "test_case") for s in subjects)
                or request.relation not in {"implements", "asserts"}):
            raise ValueError("invalid semantic screening endpoints")
        snapshot = self.screen_endpoints(request.project_id, request.image_revision_id, header.artifact_hash,
            request.relation, subjects, target)
        images.authorization.require_current(scope)
        return snapshot

    def screen_endpoints(self, project_id, image_revision_id, image_hash, predicate, subjects, target, *, pinned_heads=None):
        identities = {s.object_id for s in subjects}
        if (len(subjects) > 10000 or len(identities) != len(subjects)
                or len({s.identity_key for s in subjects}) != len(subjects)
                or predicate not in {"implements", "asserts"}
                or target.kind not in ({"acceptance_criterion"} if predicate == "asserts" else {"acceptance_criterion", "business_rule"})
                or any(s.kind != ("code_entity" if predicate == "implements" else "test_case") for s in subjects)):
            raise ValueError("invalid semantic screening corpus")
        pins = (self.heads.matching_heads(project_id, predicate, subjects, target) if subjects else ()) if pinned_heads is None else pinned_heads
        if (len(pins) > MAX_MATCHED_REVIEW_HEADS or len({p[1] for p in pins}) != len(pins)
                or tuple(sorted(pins)) != pins or any(p[0] not in identities for p in pins)):
            raise ImageRevisionIntegrityError("semantic screening exceeds its complete review-head budget")
        items = []
        for subject_id, decision_id, digest in pins:
            # Rebuild original evidence and check its current ACL; registry joins
            # are discovery hints, never authority to reuse a human decision.
            result = self.applicability.read(project_id, image_revision_id, image_hash,
                decision_id, subject_id, target.object_id, through_decision_id=decision_id)
            if result.head_decision_digest != digest or result.predicate != predicate:
                raise ImageRevisionIntegrityError("semantic screening head failed verification")
            items.append(SemanticScreeningItem(subject_id, decision_id, digest, result.claim_id,
                result.source_image_revision_id, result.decision, result.assessment.status, result.assessment.candidate_action))
        snapshot = SemanticScreeningSnapshot(project_id, image_revision_id, image_hash, predicate, subjects, target, tuple(items))
        if pinned_heads is None:
            self.require_current(snapshot)
        return snapshot

    def require_current(self, snapshot):
        current = self.heads.matching_heads(snapshot.project_id, snapshot.predicate, snapshot.subjects, snapshot.target) if snapshot.subjects else ()
        if current != snapshot.head_pins:
            raise ImageRevisionIntegrityError("semantic review heads changed; preview and confirm again")
