"""Recheck source access for historical draft commands and suppress SSE details."""
from ..quality_loop.scope_draft_inputs import SCOPE_DRAFT_TOOL
from .errors import PlatformApplicationError


SCOPE_DRAFT_RECEIPT_TOOLS = {SCOPE_DRAFT_TOOL, "query.quality.test_design_scope.draft_preview"}


class ScopeDraftReceiptAccess:
    def __init__(self, scopes):
        self.scopes = scopes

    @staticmethod
    def applies(invocation):
        return invocation.tool_id in SCOPE_DRAFT_RECEIPT_TOOLS

    def require_access(self, invocation):
        if not self.applies(invocation):
            return
        payload = invocation.input_payload
        try:
            self.scopes.drafts.require_receipt_access(payload["project_id"], payload["context_id"], payload["context_artifact_hash"])
        except (KeyError, PermissionError) as exc:
            raise PlatformApplicationError("scope_draft_receipt_denied", "Scope draft sources are not accessible.", 403) from exc
        except ValueError as exc:
            raise PlatformApplicationError("scope_draft_receipt_invalid", "Scope draft sources could not be verified.", 502) from exc

    def require_batch_access(self, invocations):
        for invocation in invocations:
            self.require_access(invocation)

    def broadcast_view(self, invocation):
        if not self.applies(invocation):
            return invocation
        result = invocation.result.model_copy(update={"scope_draft_preview": None}) if invocation.result else None
        return invocation.model_copy(deep=True, update={"result": result, "input_payload": {
            key: value for key, value in invocation.input_payload.items() if key in {"project_id", "context_id"}}})
