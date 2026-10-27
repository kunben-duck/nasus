from ...domain.quality_loop.business_rule import RULE_TOOL, BusinessRuleRevision, business_rule_identity
from .acceptance_specification_repository import PinnedRequirementAuthorityRepository
from .business_rule_models import BusinessRuleRevisionRecord


class BusinessRuleRepository(PinnedRequirementAuthorityRepository):
    record_type = BusinessRuleRevisionRecord
    revision_type = BusinessRuleRevision
    id_field = "rule_id"
    identity = staticmethod(business_rule_identity)
    tool_id = RULE_TOOL
    document_kind = "business_rule"
    required_basis = "user_confirmed_business_rule"
    event_prefix = "quality.business_rule"
    entity_type = "business_rule"
    query_key = "business-rule"
