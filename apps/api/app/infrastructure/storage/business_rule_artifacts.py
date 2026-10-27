from ...domain.quality_loop.business_rule import RULE_SCHEMA
from .acceptance_artifacts import PinnedRequirementAuthorityArtifacts


class BusinessRuleArtifacts(PinnedRequirementAuthorityArtifacts):
    schema = RULE_SCHEMA
    namespace = "business-rule-specifications"
