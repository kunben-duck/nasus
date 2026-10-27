from .errors import PlatformApplicationError
from .tool_handlers.context_packs import CONTEXT_QUERY_INPUTS, CONTEXT_AUTHORITY_BACKFILL_TOOL
from .tool_handlers.query_input import query_payload


class ToolContextPackObservationApplicationService:
    def __init__(self, invocations, application, access):
        self.invocations, self.application, self.access = invocations, application, access

    def describe(self, invocation_id, project_id):
        invocation = self.invocations.get_tool_invocation(invocation_id)
        if invocation.tool_id not in CONTEXT_QUERY_INPUTS:
            return None
        self.access.require_invocation_project_scope(invocation)
        if invocation.status != "completed":
            return None
        request = CONTEXT_QUERY_INPUTS[invocation.tool_id].model_validate(query_payload(invocation.input_payload))
        if request.project_id != project_id:
            raise PlatformApplicationError("context_project_mismatch", "Context belongs to another project.", 403)
        receipt = (getattr(invocation.result, "context_authority_backfill" if invocation.tool_id == CONTEXT_AUTHORITY_BACKFILL_TOOL
            else "context_pack") if invocation.result else None)
        if receipt is None or receipt.request != request or self.application.receipt(request) != receipt:
            raise PlatformApplicationError("context_receipt_changed", "Context receipt changed; inspect again.", 409)
        self.access.require_invocation_project_scope(invocation)
        return receipt.model_dump(mode="json")
