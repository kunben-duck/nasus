from dataclasses import asdict

from ..system_image.code_index_lifecycle import (
    CODE_INDEX_LIST_TOOL, CODE_INDEX_STATUS_TOOL, CodeIndexListInput, CodeIndexStatusInput,
    CODE_INDEX_CANCEL_TOOL, CodeIndexCancelInput,
    CodeIndexListPage, CodeIndexStatusReceipt, CodeIndexLifecycleApplicationService,
)
from .errors import PlatformApplicationError
from .actor_context import actor_scope
from .tool_models import ToolInvocation
from .invocation_resource_policy import resource_access_failure
from .tool_evidence import ToolEvidenceInvocationPort
from .tool_handlers.evidence import EvidenceToolAccessPort
from .tool_handlers.query_input import query_payload


class CodeIndexInvocationResourcePolicy:
    def __init__(self, application: CodeIndexLifecycleApplicationService):
        self.application = application

    @staticmethod
    def applies(invocation):
        return invocation.tool_id in {CODE_INDEX_LIST_TOOL, CODE_INDEX_STATUS_TOOL, CODE_INDEX_CANCEL_TOOL}

    def can_access(self, invocation, actor):
        if not self.applies(invocation):
            return True
        try:
            payload = {key: value for key, value in query_payload(invocation.input_payload).items()
                       if key not in {"confirmed_by_user", "confirmed_at"}}
            model = (CodeIndexListInput if invocation.tool_id == CODE_INDEX_LIST_TOOL else
                     CodeIndexCancelInput if invocation.tool_id == CODE_INDEX_CANCEL_TOOL else CodeIndexStatusInput)
            request = model.model_validate(payload)
            with actor_scope(actor):
                self.application.require_receipt_access(request)
            return True
        except Exception as error:
            return resource_access_failure(invocation, error)

    def broadcast_view(self, invocation: ToolInvocation) -> ToolInvocation:
        if not self.applies(invocation):
            return invocation
        # A conversation is project-shared; source-scoped receipts must be read
        # through the live authorization boundary, including historical replay.
        return invocation.model_copy(update={"input_payload": {}, "result": None,
            "idempotency_key": None, "idempotency_scope": None, "idempotency_fingerprint": None}, deep=True)


class ToolCodeIndexObservationApplicationService:
    """Never replay a saved worker status as today's lifecycle or authorization."""

    def __init__(self, invocations: ToolEvidenceInvocationPort, application: CodeIndexLifecycleApplicationService,
                 access: EvidenceToolAccessPort):
        self.invocations, self.application, self.access = invocations, application, access

    def describe(self, invocation_id, project_id):
        invocation = self.invocations.get_tool_invocation(invocation_id)
        if invocation.tool_id not in {CODE_INDEX_LIST_TOOL, CODE_INDEX_STATUS_TOOL}:
            return None
        self.access.require_invocation_project_scope(invocation)
        model = CodeIndexListInput if invocation.tool_id == CODE_INDEX_LIST_TOOL else CodeIndexStatusInput
        expected = model.model_validate(query_payload(invocation.input_payload))
        if expected.project_id != project_id:
            raise PlatformApplicationError("code_index_project_mismatch", "Code index belongs to another project.", 403)
        if invocation.status != "completed":
            return None
        receipt = invocation.result.code_index if invocation.result else None
        kind = CodeIndexListPage if invocation.tool_id == CODE_INDEX_LIST_TOOL else CodeIndexStatusReceipt
        if (not isinstance(receipt, kind) or invocation.result.status != "completed" or receipt.request != expected):
            raise PlatformApplicationError("code_index_receipt_mismatch", "Code index receipt does not match its invocation.", 409)
        current = self.application.list(expected) if isinstance(receipt, CodeIndexListPage) else self.application.read(expected)
        if isinstance(receipt, CodeIndexStatusReceipt) and receipt.status.pin != current.status.pin:
            raise PlatformApplicationError("code_index_receipt_mismatch", "Code index generation changed.", 409)
        self.access.require_invocation_project_scope(invocation)
        return {"code_index": asdict(current), "observation_policy": "current_authorized_metadata_not_saved_worker_status"}
