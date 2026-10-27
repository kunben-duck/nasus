from ..system_image.build_completions import COMPLETION_READ_TOOL, BuildCompletionInput
from .actor_context import actor_scope
from .errors import PlatformApplicationError
from .invocation_resource_policy import resource_access_failure
from .tool_handlers.query_input import query_payload
from ...domain.system_image.build_plan import BuildPlanIntegrityError


class BuildCompletionInvocationResourcePolicy:
    def __init__(self, application, previous):
        self.application, self.previous = application, previous

    def applies(self, invocation):
        return invocation.tool_id == COMPLETION_READ_TOOL or self.previous.applies(invocation)

    def can_access(self, invocation, actor):
        if invocation.tool_id != COMPLETION_READ_TOOL:
            return self.previous.can_access(invocation, actor)
        try:
            with actor_scope(actor):
                self.application.require_access(BuildCompletionInput.model_validate(query_payload(invocation.input_payload)))
            return True
        except Exception as error:
            return resource_access_failure(invocation, error)

    def broadcast_view(self, invocation):
        if invocation.tool_id != COMPLETION_READ_TOOL:
            return self.previous.broadcast_view(invocation)
        return invocation.model_copy(update={"input_payload": {}, "result": None, "idempotency_key": None,
            "idempotency_scope": None, "idempotency_fingerprint": None}, deep=True)


class ToolBuildCompletionObservationApplicationService:
    def __init__(self, invocations, application, access):
        self.invocations, self.application, self.access = invocations, application, access

    def describe(self, invocation_id, project_id, *, require_base=False):
        invocation = self.invocations.get_tool_invocation(invocation_id)
        if invocation.tool_id != COMPLETION_READ_TOOL:
            return None
        self.access.require_invocation_project_scope(invocation)
        if invocation.status != "completed":
            return None
        receipt = invocation.result.build_completion if invocation.result else None
        if receipt is None or receipt.project_id != project_id:
            raise PlatformApplicationError("completion_receipt_mismatch", "Completion receipt scope differs.", 409)
        request = BuildCompletionInput.model_validate(query_payload(invocation.input_payload))
        if require_base and request.ownership_pin is not None:
            raise BuildPlanIntegrityError("Responsibility chains must start at an original assessment, not another refinement.")
        if request.project_id != project_id:
            raise PlatformApplicationError("completion_receipt_mismatch", "Completion request scope differs.", 409)
        # The original settled goal snapshot is already fixed in this canonical
        # command. A later resume cannot rewrite the historical assessment.
        report = self.application.read(request, require_checkpoint=False)
        if self.application.receipt(request, report) != receipt:
            raise PlatformApplicationError("completion_receipt_mismatch", "Completion report failed replay verification.", 409)
        self.access.require_invocation_project_scope(invocation)
        return report
