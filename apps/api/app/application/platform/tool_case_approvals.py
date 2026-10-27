from ..quality_loop.case_approvals import CaseApprovalReviewInput
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.case_approval import CASE_APPROVAL_TOOL, CaseApprovalIntegrityError
from .actor_context import actor_scope
from .invocation_resource_policy import resource_access_failure
from .tool_handlers.query_input import query_payload


class CaseApprovalInvocationResourcePolicy:
    def __init__(self, application, previous):
        self.application, self.previous = application, previous

    def applies(self, invocation):
        return invocation.tool_id == CASE_APPROVAL_TOOL or self.previous.applies(invocation)

    def can_access(self, invocation, actor):
        if invocation.tool_id != CASE_APPROVAL_TOOL:
            return self.previous.can_access(invocation, actor)
        try:
            payload = {key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_at", "confirmed_by_user"}}
            # Runtime denial metadata is not a domain request or an approval.
            if (invocation.status == "failed" and payload.get("authorization_denied") is True
                    and invocation.result is not None and invocation.result.followup_reason == "authorization_denied"):
                for key in ("authorization_denied", "authorization_required_roles", "authorization_user_role"):
                    payload.pop(key, None)
            request = CaseApprovalReviewInput.model_validate(payload)
            with actor_scope(actor):
                self.application.require_access(request.selection())
                if invocation.status == "completed":
                    result = invocation.result
                    prefix = "test_design_case_approval:"
                    if (result is None or result.invocation_id != invocation.id or result.status != "completed"
                            or len(result.object_refs) != 1 or not result.object_refs[0].startswith(prefix)):
                        raise CaseApprovalIntegrityError("original case admission receipt is invalid")
                    value = self.application.read(request.project_id, result.object_refs[0][len(prefix):])
                    if (value["revision"]["invocation_id"] != invocation.id
                            or value["revision"]["request_hash"] != acceptance_digest(request.model_dump(mode="json"))):
                        raise CaseApprovalIntegrityError("original case admission receipt changed its request")
            return True
        except Exception as error:
            return resource_access_failure(invocation, error)

    def broadcast_view(self, invocation):
        if invocation.tool_id != CASE_APPROVAL_TOOL:
            return self.previous.broadcast_view(invocation)
        return invocation.model_copy(update={"input_payload": {}, "result": None,
            "idempotency_key": None, "idempotency_scope": None, "idempotency_fingerprint": None}, deep=True)
