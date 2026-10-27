import asyncio
from datetime import datetime, timezone

from ...quality_loop.acceptance_specifications import AcceptanceQueryInput, AcceptanceReviewInput
from ....domain.quality_loop.acceptance_specification import AC_TOOL, StaleAcceptanceSpecification
from ..tool_models import ToolResult
from .query_input import query_payload


AC_QUERY_TOOL = "query.quality.acceptance_specification"


class AcceptanceSpecificationToolHandler:
    tool_id = AC_TOOL
    query_tool = AC_QUERY_TOOL
    review_input = AcceptanceReviewInput
    result_field = "acceptance_authority"
    object_prefix = "acceptance_specification"
    label = "Acceptance authority"
    stale_reason = "stale_acceptance_authority"

    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        await self.events.emit_tool_status(invocation.id, "running", "Verifying acceptance authority and pinned source evidence", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            payload = {k: v for k, v in query_payload(invocation.input_payload).items() if k not in {"confirmed_at", "confirmed_by_user"}}
            if invocation.tool_id == self.tool_id:
                request = self.review_input.model_validate(payload)
                value = await asyncio.to_thread(self.application.review, request, invocation_id=invocation.id,
                    recorded_at=datetime.now(timezone.utc).isoformat())
                summary = self.label + " recorded for this exact image. Source projections, image publication and verified coverage are unchanged."
                result = ToolResult(invocation_id=invocation.id, status="completed", summary=summary,
                    object_refs=[f"{self.object_prefix}:{value.revision_id}"], next_recommended_tools=[self.query_tool])
            else:
                request = AcceptanceQueryInput.model_validate(payload)
                receipt = await asyncio.to_thread(self.application.receipt, request)
                summary = self.label + " inspected. This is a query-time observation, not a reusable oracle authorization."
                result = ToolResult(invocation_id=invocation.id, status="completed", summary=summary, **{self.result_field: receipt})
            self.access.require_invocation_project_scope(invocation)
        except Exception as exc:
            stale = isinstance(exc, StaleAcceptanceSpecification)
            summary = self.label + (" changed. Reload before confirming again." if stale else " failed verification. Check reviewer permission, source pins and independent oracle confirmation.")
            await self.events.emit_tool_status(invocation.id, "failed", summary, [], ToolResult(invocation_id=invocation.id, status="failed",
                summary=summary, requires_followup=stale, followup_reason=self.stale_reason if stale else None))
            return
        await self.events.emit_tool_status(invocation.id, "completed", summary, [], result)
