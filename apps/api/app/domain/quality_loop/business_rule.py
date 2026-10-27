from dataclasses import asdict, dataclass
from typing import Optional

from .acceptance_specification import AcceptanceIntegrityError, acceptance_digest


RULE_POLICY = "nasus.business-rule-authority.v1"
RULE_SCHEMA = "nasus.business-rule-specification.v1"
RULE_TOOL = "quality.business_rule.review"
RULE_QUERY_TOOL = "query.quality.business_rule"


def business_rule_identity(project_id, image_revision_id, object_id):
    return "rule_" + acceptance_digest([project_id, image_revision_id, object_id])[7:]


@dataclass(frozen=True)
class BusinessRuleRevision:
    revision_id: str
    rule_id: str
    project_id: str
    image_revision_id: str
    image_artifact_hash: str
    object_id: str
    binding_id: str
    source_revision_id: str
    document_revision_id: str
    basis_digest: str
    status: str
    previous_revision_id: Optional[str]
    sequence: int
    authority_actor: str
    invocation_id: str
    recorded_at: str
    artifact_hash: str
    policy_revision: str = RULE_POLICY

    def __post_init__(self):
        if (self.rule_id != business_rule_identity(self.project_id, self.image_revision_id, self.object_id)
                or self.status not in {"approved", "withdrawn"} or self.policy_revision != RULE_POLICY
                or type(self.sequence) is not int or not 1 <= self.sequence <= 1000
                or (self.sequence == 1) != (self.previous_revision_id is None)
                or (self.sequence == 1 and self.status == "withdrawn")):
            raise AcceptanceIntegrityError("invalid business rule revision metadata")

    @property
    def digest(self):
        return acceptance_digest(asdict(self))
