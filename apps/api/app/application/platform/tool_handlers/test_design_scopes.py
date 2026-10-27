import asyncio
from datetime import datetime, timezone

from ...quality_loop.test_design_scope_inputs import ScopeReviewInput, ScopeQueryInput
from ....domain.quality_loop.test_design_scope import SCOPE_TOOL, SCOPE_QUERY_TOOL, TestDesignScopeChanged
from ..tool_models import ToolResult
from .query_input import query_payload


class TestDesignScopeToolHandler:
    __test__ = False

    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        await self.events.emit_tool_status(invocation.id, "running", "Verifying pinned test-design scope", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            payload = {k: v for k, v in query_payload(invocation.input_payload).items() if k not in {"confirmed_at", "confirmed_by_user"}}
            if invocation.tool_id == SCOPE_TOOL:
                request = ScopeReviewInput.model_validate(payload)
                value = await asyncio.to_thread(self.application.review, request, invocation_id=invocation.id,
                    recorded_at=datetime.now(timezone.utc).isoformat())
                result = ToolResult(invocation_id=invocation.id, status="completed",
                    summary="Test-design scope reviewed. Generation, execution and verified coverage remain separate gates.",
                    object_refs=["test_design_scope:" + value["revision_id"]], next_recommended_tools=[SCOPE_QUERY_TOOL])
            else:
                receipt = await asyncio.to_thread(self.application.receipt, ScopeQueryInput.model_validate(payload))
                result = ToolResult(invocation_id=invocation.id, status="completed", test_design_scope=receipt,
                    summary="Test-design scope metadata inspected; revalidate before using it.")
            self.access.require_invocation_project_scope(invocation)
        except Exception as exc:
            stale = isinstance(exc, TestDesignScopeChanged)
            result = ToolResult(invocation_id=invocation.id, status="failed", requires_followup=stale,
                followup_reason="test_design_scope_changed" if stale else None,
                summary="Test-design scope changed; reload before confirming." if stale else
                    "Scope review failed. Verify reviewer access, exact context pins, complete obligations and independent confirmation.")
        await self.events.emit_tool_status(invocation.id, result.status, result.summary, [], result)
