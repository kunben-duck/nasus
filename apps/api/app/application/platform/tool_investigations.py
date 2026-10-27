from ..system_image.investigations import INVESTIGATE_TOOL, INVESTIGATION_READ_TOOL, InvestigationInput, InvestigationReadInput
from .actor_context import actor_scope
from .errors import PlatformApplicationError
from .invocation_resource_policy import resource_access_failure
from .tool_handlers.query_input import query_payload


class InvestigationInvocationResourcePolicy:
    def __init__(self, application, previous):
        self.application, self.previous = application, previous

    def applies(self, invocation):
        return invocation.tool_id in {INVESTIGATE_TOOL, INVESTIGATION_READ_TOOL} or self.previous.applies(invocation)

    def can_access(self, invocation, actor):
        if invocation.tool_id not in {INVESTIGATE_TOOL, INVESTIGATION_READ_TOOL}:
            return self.previous.can_access(invocation, actor)
        try:
            body = {key: value for key, value in query_payload(invocation.input_payload).items()
                    if key not in {"confirmed_at", "confirmed_by_user"}}
            with actor_scope(actor):
                if invocation.tool_id == INVESTIGATE_TOOL:
                    self.application.require_access(InvestigationInput.model_validate(body))
                else:
                    request = InvestigationReadInput.model_validate(body)
                    record = self.application.repository.read(request.project_id, request.revision_id)
                    self.application.require_access(record.request)
            return True
        except Exception as error:
            return resource_access_failure(invocation, error)

    def broadcast_view(self, invocation):
        if invocation.tool_id not in {INVESTIGATE_TOOL, INVESTIGATION_READ_TOOL}:
            return self.previous.broadcast_view(invocation)
        return invocation.model_copy(update={"input_payload": {}, "result": None,
            "idempotency_key": None, "idempotency_scope": None, "idempotency_fingerprint": None}, deep=True)


class ToolInvestigationObservationApplicationService:
    def __init__(self, invocations, application, access):
        self.invocations, self.application, self.access = invocations, application, access

    def describe(self, invocation_id, project_id):
        invocation = self.invocations.get_tool_invocation(invocation_id)
        if invocation.tool_id not in {INVESTIGATE_TOOL, INVESTIGATION_READ_TOOL}:
            return None
        self.access.require_invocation_project_scope(invocation)
        if invocation.status != "completed":
            return None
        receipt = invocation.result.investigation if invocation.result else None
        if receipt is None or receipt.project_id != project_id:
            raise PlatformApplicationError("investigation_receipt_mismatch", "Investigation receipt does not match its project.", 409)
        stored = self.application.read(project_id, receipt.revision_id)
        body = {key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_at", "confirmed_by_user"}}
        expected = (InvestigationInput.model_validate(body) == stored.request if invocation.tool_id == INVESTIGATE_TOOL
                    else InvestigationReadInput.model_validate(body) == InvestigationReadInput(project_id=project_id, revision_id=stored.revision_id))
        if not expected or stored.revision_hash != receipt.revision_hash:
            raise PlatformApplicationError("investigation_receipt_mismatch", "Investigation receipt does not match its command.", 409)
        self.access.require_invocation_project_scope(invocation)
        return self.application.describe(stored)
