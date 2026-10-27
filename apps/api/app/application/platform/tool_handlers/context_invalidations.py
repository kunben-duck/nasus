import asyncio
from datetime import datetime, timezone

from ...system_image.context_invalidations import ContextInvalidateInput, context_invalidation_query_keys
from ....domain.system_image.context_invalidation import ContextInvalidationChanged
from ..tool_models import ToolResult
from .query_input import query_payload


class ContextInvalidationToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        await self.events.emit_tool_status(invocation.id, "running", "Verifying the complete fixed dependency closure before invalidation", [])
        query_keys = []
        try:
            self.access.require_invocation_project_scope(invocation)
            request = ContextInvalidateInput.model_validate({k: v for k, v in query_payload(invocation.input_payload).items()
                if k not in {"confirmed_by_user", "confirmed_at"}})
            value = await asyncio.to_thread(self.application.invalidate, request, invocation_id=invocation.id,
                recorded_at=datetime.now(timezone.utc).isoformat())
            self.access.require_invocation_project_scope(invocation)
            query_keys = context_invalidation_query_keys(request.project_id)
            result = ToolResult(invocation_id=invocation.id, status="completed",
                summary="Source change invalidation recorded for the exact image revision. Current scope, generation and mapping use is blocked; historical artifacts, approvals and other image revisions are unchanged.",
                object_refs=["context_invalidation:" + value["invalidation_id"]],
                next_recommended_tools=["query.system_image.context.read", "query.quality.test_design_scope"])
        except Exception as exc:
            changed = isinstance(exc, ContextInvalidationChanged)
            result = ToolResult(invocation_id=invocation.id, status="failed",
                summary="Dependency inventory changed. Inspect and confirm again." if changed else
                    "Context invalidation could not be verified. Check current source access, reviewer role and exact confirmation.",
                requires_followup=True, followup_reason="context_invalidation_changed" if changed else "context_invalidation_verification_failed",
                next_recommended_tools=["query.system_image.context.change_impact"])
        await self.events.emit_tool_status(invocation.id, result.status, result.summary, query_keys, result)
