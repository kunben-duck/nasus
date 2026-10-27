from ...quality_loop.business_rules import BusinessRuleReviewInput
from ....domain.quality_loop.business_rule import RULE_TOOL, RULE_QUERY_TOOL
from .acceptance_specifications import AcceptanceSpecificationToolHandler


class BusinessRuleToolHandler(AcceptanceSpecificationToolHandler):
    tool_id = RULE_TOOL
    query_tool = RULE_QUERY_TOOL
    review_input = BusinessRuleReviewInput
    result_field = "business_rule_authority"
    object_prefix = "business_rule"
    label = "Business rule authority"
    stale_reason = "stale_business_rule_authority"
