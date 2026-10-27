from ..system_image.publications import PublicationTarget, PublicationHeadInput, RollbackTarget
from ...domain.system_image.publication import PUBLICATION_QUERY_TOOL, PUBLICATION_HEAD_TOOL, ROLLBACK_QUERY_TOOL, PublicationChanged
from .errors import PlatformApplicationError
from .tool_handlers.query_input import query_payload


class ToolPublicationObservationApplicationService:
    def __init__(self, invocations, application, access):
        self.invocations, self.application, self.access = invocations, application, access

    def describe(self, invocation_id, project_id):
        invocation = self.invocations.get_tool_invocation(invocation_id)
        if invocation.tool_id not in {PUBLICATION_QUERY_TOOL, PUBLICATION_HEAD_TOOL, ROLLBACK_QUERY_TOOL}:
            return None
        self.access.require_invocation_project_scope(invocation)
        if invocation.status != "completed":
            return None
        head = invocation.tool_id == PUBLICATION_HEAD_TOOL
        model = PublicationHeadInput if head else RollbackTarget if invocation.tool_id == ROLLBACK_QUERY_TOOL else PublicationTarget
        request = model.model_validate(query_payload(invocation.input_payload))
        if request.project_id != project_id:
            raise PlatformApplicationError("publication_scope_mismatch", "Publication belongs to another project.", 403)
        receipt = (invocation.result.image_publication_head if head else invocation.result.image_publication) if invocation.result else None
        try:
            current = self.application.head_receipt(request) if head else self.application.receipt(request)
        except PublicationChanged as exc:
            raise PlatformApplicationError("publication_preview_changed", "Publication preview changed; inspect again.", 409) from exc
        if receipt is None or receipt.request != request or current != receipt:
            raise PlatformApplicationError("publication_preview_changed", "Publication preview changed; inspect again.", 409)
        self.access.require_invocation_project_scope(invocation)
        return receipt.model_dump(mode="json")
