from __future__ import annotations

from dataclasses import dataclass


SEMANTIC_APPLICABILITY_POLICY = "nasus.semantic-decision-applicability.v1"


@dataclass(frozen=True)
class SemanticEndpointIdentity:
    object_id: str
    binding_id: str
    entity_id: str
    revision_id: str
    source_revision_id: str
    kind: str
    identity_basis: str

    def __post_init__(self):
        for key in ("object_id", "binding_id", "entity_id", "revision_id", "source_revision_id"):
            value = getattr(self, key)
            if type(value) is not str or not value or len(value) > 128:
                raise ValueError("invalid semantic endpoint identity")
        if (self.kind not in {"code_entity", "test_case", "acceptance_criterion", "business_rule"}
                or self.identity_basis not in {"registered_symbol", "explicit_id", "source_occurrence", "ambiguous"}
                or (self.kind == "code_entity") != (self.identity_basis == "registered_symbol")):
            raise ValueError("invalid semantic endpoint identity basis")

    @property
    def identity_key(self):
        return self.binding_id, self.entity_id, self.kind

    @property
    def revision_key(self):
        return self.identity_key, self.revision_id, self.source_revision_id


@dataclass(frozen=True)
class SemanticApplicabilityAssessment:
    status: str
    candidate_action: str
    approval_transferred: bool = False
    policy_revision: str = SEMANTIC_APPLICABILITY_POLICY


def assess_semantic_decision(decision, original_subject, original_target, subject, target):
    if decision not in {"accept", "reject", "defer"}:
        raise ValueError("unsupported semantic decision")
    pairs = ((original_subject, subject), (original_target, target))
    if any(old.identity_key != new.identity_key for old, new in pairs):
        return SemanticApplicabilityAssessment("different_endpoints", "resolve_identity_before_transfer")
    if any(old.identity_basis != new.identity_basis for old, new in pairs):
        return SemanticApplicabilityAssessment("identity_unresolved", "resolve_identity_before_transfer")
    if any(old.revision_key != new.revision_key for old, new in pairs):
        if any(old.identity_basis in {"source_occurrence", "ambiguous"}
               for old, new in pairs if old.revision_key != new.revision_key):
            return SemanticApplicabilityAssessment("identity_unresolved", "resolve_identity_before_transfer")
        # A registry identity is lineage, not proof that a changed implementation
        # or expectation still satisfies the previously reviewed relationship.
        return SemanticApplicabilityAssessment("stale_requires_review", "revalidate_before_review")
    if decision == "reject":
        return SemanticApplicabilityAssessment("rejected_same_revisions", "exclude_from_unreviewed_candidates")
    return SemanticApplicabilityAssessment("same_revisions_review_required", "review_before_acceptance")
