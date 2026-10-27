from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from .reference_links import ReferenceAssertion
from .source_snapshots import snapshot_digest


LINK_REVIEW_POLICY = "nasus.explicit-reference-review.v1"
REVIEW_LINK_TOOL = "system_image.links.review"


class StaleLinkDecision(ValueError):
    pass


def assertion_evidence_digest(assertion: ReferenceAssertion) -> str:
    return snapshot_digest({"subject_revision_id": assertion.subject_revision_id,
        "object_revision_id": assertion.object_revision_id,
        "subject_evidence_ids": assertion.subject_evidence_ids, "object_evidence_ids": assertion.object_evidence_ids})


@dataclass(frozen=True)
class LinkDecision:
    decision_id: str
    project_id: str
    proposal_id: str
    assertion_id: str
    image_revision_id: str
    proposal_digest: str
    assertion_digest: str
    evidence_digest: str
    decision: str
    reviewer_actor: str
    reason: str
    recorded_at: str
    invocation_id: str
    previous_decision_id: Optional[str]
    sequence: int
    policy_revision: str = LINK_REVIEW_POLICY
    applicability: str = "selected_manifest_only_not_business_coverage"

    def __post_init__(self):
        if self.decision not in {"accept", "reject", "defer"}:
            raise ValueError("unknown link decision")
        if not self.reason.strip() or len(self.reason) > 2000 or not self.reviewer_actor:
            raise ValueError("review requires an actor and a bounded nonempty reason")
        if (type(self.sequence) is not int or not 1 <= self.sequence <= 1000
                or (self.sequence == 1) != (self.previous_decision_id is None)):
            raise ValueError("invalid decision chain")
        if self.policy_revision != LINK_REVIEW_POLICY or self.applicability != "selected_manifest_only_not_business_coverage":
            raise ValueError("unsupported reference review policy")

    @property
    def digest(self) -> str:
        return snapshot_digest(asdict(self))


def require_expected_decision(previous: Optional[LinkDecision], expected_id: Optional[str]) -> None:
    if (previous.decision_id if previous else None) != expected_id:
        raise StaleLinkDecision("Review changed; reload before submitting another decision.")
