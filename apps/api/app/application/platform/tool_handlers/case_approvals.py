import asyncio
from datetime import datetime, timezone

from ...quality_loop.case_approvals import CaseApprovalReviewInput
from ....domain.quality_loop.case_approval import CaseApprovalChanged
from ..tool_models import ToolResult
from .query_input import query_payload


class CaseApprovalToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        keys = []
        await self.events.emit_tool_status(invocation.id, "running", "Verifying independent case admission", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            request = CaseApprovalReviewInput.model_validate({key: value for key, value in
                query_payload(invocation.input_payload).items() if key not in {"confirmed_at", "confirmed_by_user"}})
            value = await asyncio.to_thread(self.application.review, request, invocation_id=invocation.id,
                recorded_at=datetime.now(timezone.utc).isoformat())
            self.access.require_invocation_project_scope(invocation)
            result = ToolResult(invocation_id=invocation.id, status="completed",
                summary="Independent case admission recorded. No target execution or verified business coverage granted.",
                object_refs=["test_design_case_approval:" + value["revision_id"]])
            keys = [["test-design-case-approvals", request.project_id]]
        except Exception as error:
            stale = isinstance(error, CaseApprovalChanged)
            result = ToolResult(invocation_id=invocation.id, status="failed", requires_followup=stale,
                followup_reason="case_admission_changed" if stale else None,
                summary="Case admission changed; inspect again before confirming." if stale else
                    "Case admission failed. Verify source access, reviewer role, fixed inputs and independent confirmation.")
        await self.events.emit_tool_status(invocation.id, result.status, result.summary,
            keys if result.status == "completed" else [], result)
