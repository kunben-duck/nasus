import asyncio
from datetime import datetime, timezone

from ...quality_loop.automation_script_review_inputs import ScriptReviewQuery, ScriptReviewRequest
from ....domain.quality_loop.automation_script_review import SCRIPT_REVIEW_QUERY_TOOL, SCRIPT_REVIEW_TOOL, ScriptReviewChanged
from ..tool_models import ToolResult
from .query_input import query_payload


class AutomationScriptReviewToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        keys = []
        await self.events.emit_tool_status(invocation.id, "running", "Verifying exact DSL actions and independent oracle review", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            payload = {key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}}
            if invocation.tool_id == SCRIPT_REVIEW_TOOL:
                request = ScriptReviewRequest.model_validate(payload)
                value = await asyncio.to_thread(self.application.review, request, invocation_id=invocation.id,
                    recorded_at=datetime.now(timezone.utc).isoformat())
                result = ToolResult(invocation_id=invocation.id, status="completed",
                    summary="Independent script review recorded; target/build/environment, fixtures and RunPlan remain required.",
                    object_refs=["automation_script_review:" + value["revision_id"]], next_recommended_tools=[SCRIPT_REVIEW_QUERY_TOOL])
                keys = [["automation-script-reviews", request.project_id, request.script_revision_id]]
            else:
                receipt = await asyncio.to_thread(self.application.receipt, ScriptReviewQuery.model_validate(payload))
                result = ToolResult(invocation_id=invocation.id, status="completed", automation_script_review=receipt,
                    summary="Script review metadata only; revalidate before use. No execution authority.")
            self.access.require_invocation_project_scope(invocation)
        except Exception as exc:
            stale = isinstance(exc, ScriptReviewChanged)
            result = ToolResult(invocation_id=invocation.id, status="failed", requires_followup=stale,
                followup_reason="automation_review_changed" if stale else None,
                summary="Script review changed; reload before confirming." if stale else
                    "Script review unavailable. Verify reviewer/source access, exact actions/oracles and fresh confirmation.")
        await self.events.emit_tool_status(invocation.id, result.status, result.summary, keys if result.status == "completed" else [], result)
