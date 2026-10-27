from typing import Literal, Optional

from pydantic import Field, StrictStr

from ...domain.quality_loop.business_rule import RULE_POLICY, RULE_SCHEMA, business_rule_identity
from .acceptance_specifications import AcceptanceQueryInput, AcceptanceReviewInput, PinnedRequirementAuthorityService


class BusinessRuleReviewInput(AcceptanceReviewInput):
    policy_revision: Literal[RULE_POLICY]
    authority_basis: Optional[Literal["user_confirmed_business_rule"]]


class BusinessRuleAuthorityReceipt(AcceptanceQueryInput):
    rule_id: StrictStr
    basis_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    head_revision_id: Optional[StrictStr]
    head_artifact_hash: Optional[StrictStr]
    status: Literal["unapproved", "approved", "withdrawn"]
    policy_revision: Literal[RULE_POLICY] = RULE_POLICY
    applicability: Literal["exact_image_only"] = "exact_image_only"
    observation: Literal["query_time_not_live"] = "query_time_not_live"


class BusinessRuleApplicationService(PinnedRequirementAuthorityService):
    id_field = "rule_id"
    identity = staticmethod(business_rule_identity)
    policy = RULE_POLICY
    schema = RULE_SCHEMA
    review_input = BusinessRuleReviewInput
    receipt_type = BusinessRuleAuthorityReceipt
    required_basis = "user_confirmed_business_rule"
