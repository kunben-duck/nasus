import asyncio

from ...quality_loop.scope_draft_inputs import SCOPE_DRAFT_TOOL, ScopeDraftRequest, ScopeDraftSelection
from ..tool_models import ToolResult
from .query_input import query_payload


class ScopeDraftToolHandler:
    def __init__(self, scopes, events, access):
        self.scopes, self.events, self.access = scopes, events, access

    async def handle(self, invocation):
        await self.events.emit_tool_status(invocation.id, "running", "Checking the fixed scope draft and model budget", [])
        keys = []
        try:
            self.access.require_invocation_project_scope(invocation)
            payload = {key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}}
            if invocation.tool_id == SCOPE_DRAFT_TOOL:
                await self.scopes.drafts.execute(ScopeDraftRequest.model_validate(payload), invocation_id=invocation.id)
                result = ToolResult(invocation_id=invocation.id, status="completed",
                    summary="Model scope draft saved. Review its obligations and gaps before independently approving scope.",
                    object_refs=["scope_draft:" + invocation.id], next_recommended_tools=["query.quality.test_design_scope"])
                keys = [["scope-drafts", payload["project_id"], payload["context_id"]]]
            else:
                preview = await asyncio.to_thread(self.scopes.drafts.preview, ScopeDraftSelection.model_validate(payload))
                result = ToolResult(invocation_id=invocation.id, status="completed", scope_draft_preview=preview,
                    summary="Scope draft budget preview only; no model call or approval.")
            self.access.require_invocation_project_scope(invocation)
        except Exception:
            result = ToolResult(invocation_id=invocation.id, status="failed",
                summary="Scope model draft unavailable. Check confirmed context, tested model, source permission and budget. Reserved calls are never automatically resent.")
        await self.events.emit_tool_status(invocation.id, result.status, result.summary, keys, result)
