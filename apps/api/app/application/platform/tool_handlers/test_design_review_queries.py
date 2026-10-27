import asyncio

from ...quality_loop.test_design_review_queries import ReviewDraftListInput
from ..tool_models import ToolResult
from .query_input import query_payload


class TestDesignReviewQueryHandler:
    __test__ = False

    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        await self.events.emit_tool_status(invocation.id, "running", "Checking archived drafts and reviewer access", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            request = ReviewDraftListInput.model_validate(query_payload(invocation.input_payload))
            receipt = await asyncio.to_thread(self.application.review_receipt, request)
            self.access.require_invocation_project_scope(invocation)
            result = ToolResult(invocation_id=invocation.id, status="completed", test_design_review_drafts=receipt,
                summary="Archived draft IDs inspected. Revalidate this page before use; generation and execution remain separate gates.")
        except Exception:
            result = ToolResult(invocation_id=invocation.id, status="failed",
                summary="Draft discovery unavailable. Check current reviewer access, original source permissions and archive integrity.")
        await self.events.emit_tool_status(invocation.id, result.status, result.summary, [], result)
