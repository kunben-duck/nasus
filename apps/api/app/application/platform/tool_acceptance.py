from ..quality_loop.acceptance_specifications import AcceptanceQueryInput
from .errors import PlatformApplicationError
from .tool_handlers.acceptance_specifications import AC_QUERY_TOOL
from .tool_handlers.query_input import query_payload
from ...domain.quality_loop.business_rule import RULE_QUERY_TOOL


class ToolAcceptanceObservationApplicationService:
    def __init__(self, invocations, application, access, *, rules=None):
        self.invocations, self.application, self.access = invocations, application, access
        self.rules = rules

    def describe(self, invocation_id, project_id):
        invocation = self.invocations.get_tool_invocation(invocation_id)
        if invocation.tool_id not in {AC_QUERY_TOOL, RULE_QUERY_TOOL}:
            return None
        application = self.rules if invocation.tool_id == RULE_QUERY_TOOL else self.application
        if application is None:
            raise PlatformApplicationError("authority_not_configured", "Authority query is unavailable.", 503)
        self.access.require_invocation_project_scope(invocation)
        if invocation.status != "completed":
            return None
        request = AcceptanceQueryInput.model_validate(query_payload(invocation.input_payload))
        if request.project_id != project_id:
            raise PlatformApplicationError("acceptance_project_mismatch", "Acceptance query belongs to another project.", 403)
        field = "business_rule_authority" if invocation.tool_id == RULE_QUERY_TOOL else "acceptance_authority"
        receipt = getattr(invocation.result, field) if invocation.result else None
        if receipt is None or any(getattr(receipt, key) != value for key, value in request.model_dump().items()):
            raise PlatformApplicationError("acceptance_receipt_mismatch", "Acceptance receipt does not match its invocation.", 409)
        application.verify_receipt(receipt)
        self.access.require_invocation_project_scope(invocation)
        # Only IDs and fixed query-time status; never source text or the oracle.
        return receipt.model_dump(mode="json")
