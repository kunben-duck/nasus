from ..system_image.index_inputs import IndexSelection, INDEX_PREVIEW_TOOL
from ..system_image.context_retrieval_inputs import ContextRetrievalSelection, CONTEXT_RETRIEVAL_PREVIEW_TOOL
from ..system_image.context_retrieval_ports import CONTEXT_RETRIEVAL_QUERY_TOOL
from .errors import PlatformApplicationError
from .tool_handlers.query_input import query_payload


class ToolIndexObservationApplicationService:
    """A historical tool receipt cannot itself authorize new model egress."""

    def __init__(self, invocations, application, access, retrievals=None):
        self.invocations, self.application, self.access = invocations, application, access
        self.retrievals = retrievals

    def describe(self, invocation_id, project_id):
        invocation = self.invocations.get_tool_invocation(invocation_id)
        if invocation.tool_id not in {INDEX_PREVIEW_TOOL, CONTEXT_RETRIEVAL_PREVIEW_TOOL, CONTEXT_RETRIEVAL_QUERY_TOOL}:
            return None
        self.access.require_invocation_project_scope(invocation)
        if invocation.status != "completed":
            return None
        if invocation.tool_id == CONTEXT_RETRIEVAL_QUERY_TOOL:
            if invocation.input_payload.get("project_id") != project_id or self.retrievals is None:
                raise PlatformApplicationError("index_scope_mismatch", "Retrieval belongs to another project.", 403)
            current = self.retrievals.read(project_id, invocation.input_payload["invocation_id"])
            if not invocation.result or invocation.result.context_retrieval_result != current:
                raise PlatformApplicationError("retrieval_receipt_mismatch", "Retrieval receipt changed.", 409)
            self.application.require_replay_current(project_id, current)
            self.access.require_invocation_project_scope(invocation)
            return current
        context = invocation.tool_id == CONTEXT_RETRIEVAL_PREVIEW_TOOL
        schema = ContextRetrievalSelection if context else IndexSelection
        request = schema.model_validate(query_payload(invocation.input_payload))
        if request.project_id != project_id:
            raise PlatformApplicationError("index_scope_mismatch", "Index belongs to another project.", 403)
        receipt = (invocation.result.context_retrieval_preview if context else invocation.result.index_preview) if invocation.result else None
        current = self.application.context_retrieval_preview(request) if context else self.application.preview(request)
        if receipt is None or current != receipt:
            raise PlatformApplicationError("index_preview_changed", "Index preview changed; inspect and confirm again.", 409)
        self.access.require_invocation_project_scope(invocation)
        return current
