from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from .image_revision import require_digest
from .source_snapshots import snapshot_digest


SEMANTIC_REVIEW_POLICY = "nasus.semantic-link-review.v1"
SEMANTIC_REVIEW_TOOL = "system_image.links.review_semantic"


@dataclass(frozen=True)
class SemanticAssertion:
    project_id: str
    image_revision_id: str
    image_artifact_hash: str
    evaluation_id: str
    evaluation_artifact_hash: str
    input_digest: str
    subject_object_id: str
    subject_revision_id: str
    object_id: str
    object_revision_id: str
    predicate: str
    assessment: str
    subject_evidence_ids: tuple[str, ...]
    object_evidence_ids: tuple[str, ...]
    evidence_digest: str
    oracle_digest: Optional[str]
    method_version: str = "nasus.semantic-link-judgment.v1"
    semantic_kind: str = "inferred"
    status: str = "proposed"
    authority_status: str = "pending_confirmation"
    applicability: str = "selected_image_only_not_verified_coverage"

    def __post_init__(self):
        for key in ("project_id", "image_revision_id", "evaluation_id", "subject_object_id", "subject_revision_id", "object_id", "object_revision_id"):
            value = getattr(self, key)
            if not isinstance(value, str) or not value or len(value) > 128:
                raise ValueError("invalid semantic assertion identity")
        for key in ("image_artifact_hash", "evaluation_artifact_hash", "input_digest", "evidence_digest"):
            require_digest(getattr(self, key))
        if self.oracle_digest is not None:
            require_digest(self.oracle_digest)
        if (self.predicate not in {"implements", "asserts"} or self.assessment not in {"supports", "contradicts", "unrelated", "unknown"}
                or self.semantic_kind != "inferred" or self.status != "proposed" or self.authority_status != "pending_confirmation"
                or self.applicability != "selected_image_only_not_verified_coverage" or self.method_version != "nasus.semantic-link-judgment.v1"):
            raise ValueError("unsupported semantic assertion policy")
        for values in (self.subject_evidence_ids, self.object_evidence_ids):
            if (type(values) is not tuple or not 1 <= len(values) <= 128 or len(set(values)) != len(values)
                    or any(type(value) is not str or not value or len(value) > 128 for value in values)):
                raise ValueError("invalid semantic assertion evidence")

    @property
    def digest(self):
        return snapshot_digest(asdict(self))

    @property
    def assertion_id(self):
        return "sa_" + self.digest.removeprefix("sha256:")

    @property
    def claim_id(self):
        # A new model evaluation cannot reset the human decision for the same
        # frozen endpoint pair. A different image/revision needs a new review.
        keys = ("project_id", "image_revision_id", "image_artifact_hash", "subject_object_id", "subject_revision_id", "object_id", "object_revision_id", "predicate")
        return "sc_" + snapshot_digest({key: getattr(self, key) for key in keys}).removeprefix("sha256:")

    @property
    def can_accept(self):
        return self.assessment == "supports" and (self.predicate != "asserts" or self.oracle_digest is not None)

    def require_decision(self, decision):
        if decision not in {"accept", "reject", "defer"} or (decision == "accept" and not self.can_accept):
            raise ValueError("only a supported, grounded semantic relation can be accepted")


def stored_semantic_assertion(payload):
    return SemanticAssertion(**{**payload, "subject_evidence_ids": tuple(payload["subject_evidence_ids"]),
                                "object_evidence_ids": tuple(payload["object_evidence_ids"])})


@dataclass(frozen=True)
class SemanticDecision:
    decision_id: str
    project_id: str
    claim_id: str
    assertion_id: str
    assertion_digest: str
    evidence_digest: str
    evaluation_id: str
    image_revision_id: str
    decision: str
    reason: str
    reviewer_actor: str
    recorded_at: str
    invocation_id: str
    previous_decision_id: Optional[str]
    sequence: int
    policy_revision: str = SEMANTIC_REVIEW_POLICY
    applicability: str = "selected_image_only_not_verified_coverage"

    def __post_init__(self):
        for key in ("decision_id", "project_id", "claim_id", "assertion_id", "evaluation_id", "image_revision_id", "reviewer_actor", "invocation_id", "recorded_at"):
            value = getattr(self, key)
            if type(value) is not str or not value or len(value) > 128:
                raise ValueError("invalid semantic decision identity")
        if (self.previous_decision_id is not None and
                (type(self.previous_decision_id) is not str or not self.previous_decision_id or len(self.previous_decision_id) > 128)):
            raise ValueError("invalid semantic decision predecessor")
        if (self.decision not in {"accept", "reject", "defer"} or type(self.reason) is not str or not self.reason.strip() or len(self.reason) > 2000
                or type(self.sequence) is not int or not 1 <= self.sequence <= 1000
                or (self.sequence == 1) != (self.previous_decision_id is None)
                or self.policy_revision != SEMANTIC_REVIEW_POLICY or self.applicability != "selected_image_only_not_verified_coverage"):
            raise ValueError("invalid semantic decision")
        require_digest(self.assertion_digest)
        require_digest(self.evidence_digest)

    @property
    def digest(self):
        return snapshot_digest(asdict(self))
