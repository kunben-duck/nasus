from ..system_image.structure_cancel_inputs import STRUCTURE_CANCEL_TOOL, StructureCancelInput
from .actor_context import actor_scope
from .invocation_resource_policy import resource_access_failure
from .tool_handlers.query_input import query_payload


class StructureCancellationInvocationResourcePolicy:
    """Compose live source access and private broadcast with existing policies."""
    def __init__(self, application, previous):
        self.application, self.previous = application, previous

    def applies(self, invocation):
        return invocation.tool_id == STRUCTURE_CANCEL_TOOL or self.previous.applies(invocation)

    def can_access(self, invocation, actor):
        if invocation.tool_id != STRUCTURE_CANCEL_TOOL:
            return self.previous.can_access(invocation, actor)
        try:
            request = StructureCancelInput.model_validate({key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}})
            with actor_scope(actor):
                self.application.require_access(request)
            return True
        except Exception as error:
            return resource_access_failure(invocation, error)

    def broadcast_view(self, invocation):
        if invocation.tool_id != STRUCTURE_CANCEL_TOOL:
            return self.previous.broadcast_view(invocation)
        return invocation.model_copy(update={"input_payload": {}, "result": None,
            "idempotency_key": None, "idempotency_scope": None, "idempotency_fingerprint": None}, deep=True)
