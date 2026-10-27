from ..system_image.gap_ownership import ASSIGN_GAPS_TOOL, GapOwnershipInput
from .actor_context import actor_scope
from .errors import PlatformApplicationError
from .invocation_resource_policy import resource_access_failure
from .tool_handlers.query_input import query_payload


class GapOwnershipInvocationResourcePolicy:
    def __init__(self, application, previous):
        self.application, self.previous = application, previous

    def applies(self, invocation):
        return invocation.tool_id == ASSIGN_GAPS_TOOL or self.previous.applies(invocation)

    def can_access(self, invocation, actor):
        if invocation.tool_id != ASSIGN_GAPS_TOOL:
            return self.previous.can_access(invocation, actor)
        try:
            body = query_payload(invocation.input_payload)
            body.pop("confirmed_at", None)
            body.pop("confirmed_by_user", None)
            with actor_scope(actor):
                self.application.require_access(GapOwnershipInput.model_validate(body))
            return True
        except Exception as error:
            return resource_access_failure(invocation, error)

    def broadcast_view(self, invocation):
        if invocation.tool_id != ASSIGN_GAPS_TOOL:
            return self.previous.broadcast_view(invocation)
        return invocation.model_copy(update={"input_payload": {}, "result": None, "idempotency_key": None,
            "idempotency_scope": None, "idempotency_fingerprint": None}, deep=True)


class ToolGapOwnershipObservationApplicationService:
    def __init__(self, invocations, application, access):
        self.invocations, self.application, self.access = invocations, application, access

    def describe(self, invocation_id, project_id):
        invocation = self.invocations.get_tool_invocation(invocation_id)
        if invocation.tool_id != ASSIGN_GAPS_TOOL:
            return None
        self.access.require_invocation_project_scope(invocation)
        if invocation.status != "completed":
            return None
        receipt = invocation.result.build_gap_ownership if invocation.result else None
        body = query_payload(invocation.input_payload)
        body.pop("confirmed_at", None)
        body.pop("confirmed_by_user", None)
        request = GapOwnershipInput.model_validate(body)
        if receipt is None or request.project_id != project_id or receipt.project_id != project_id:
            raise PlatformApplicationError("gap_ownership_receipt_mismatch", "Gap responsibility scope differs.", 409)
        self.application.require_access(request)
        view = self.application.read(project_id, request.completion_invocation_id, revision_id=receipt.revision_id)
        revision = next((item for item in view["history"] if item["revision_id"] == receipt.revision_id), None)
        if (receipt.completion_invocation_id != request.completion_invocation_id
                or receipt.completion_report_hash != request.completion_report_hash
                or view["revision_hash"] != receipt.revision_hash or revision is None
                or revision["invocation_id"] != invocation_id
                or revision["assignments"] != request.model_dump(mode="json")["assignments"]):
            raise PlatformApplicationError("gap_ownership_receipt_mismatch", "Gap responsibility failed replay verification.", 409)
        self.access.require_invocation_project_scope(invocation)
        return view
