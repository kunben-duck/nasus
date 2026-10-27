import asyncio
from datetime import datetime, timezone

from ...quality_loop.test_design_mapping_inputs import MappingReviewInput, MappingQueryInput
from ...quality_loop.mapping_finalization_inputs import MappingFinalizeInput
from ...quality_loop.test_design_mapping_pins import mapping_review_query_keys
from ....domain.quality_loop.mapping_part_sets import FINALIZE_TOOL
from ....domain.quality_loop.test_design_mapping import MAPPING_TOOL, MAPPING_QUERY_TOOL, TestDesignMappingChanged
from ..tool_models import ToolResult
from .query_input import query_payload


class TestDesignMappingToolHandler:
    __test__ = False

    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        query_keys = []
        await self.events.emit_tool_status(invocation.id, "running", "Verifying pinned assertion mapping", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            payload = {key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_at", "confirmed_by_user"}}
            if invocation.tool_id in {MAPPING_TOOL, FINALIZE_TOOL}:
                final = invocation.tool_id == FINALIZE_TOOL
                request = (MappingFinalizeInput if final else MappingReviewInput).model_validate(payload)
                value = await asyncio.to_thread(self.application.finalize if final else self.application.review, request, invocation_id=invocation.id,
                    recorded_at=datetime.now(timezone.utc).isoformat())
                result = ToolResult(invocation_id=invocation.id, status="completed",
                    summary="Independent assertion mapping recorded. Automation, target execution and pass remain separate gates.",
                    object_refs=["test_design_mapping:" + value["revision_id"]], next_recommended_tools=[MAPPING_QUERY_TOOL])
                query_keys = mapping_review_query_keys(request.project_id)
            else:
                receipt = await asyncio.to_thread(self.application.receipt, MappingQueryInput.model_validate(payload))
                result = ToolResult(invocation_id=invocation.id, status="completed", test_design_mapping=receipt,
                    summary="Assertion mapping metadata inspected; revalidate before consuming it.")
            self.access.require_invocation_project_scope(invocation)
        except Exception as exc:
            stale = isinstance(exc, TestDesignMappingChanged)
            result = ToolResult(invocation_id=invocation.id, status="failed", requires_followup=stale,
                followup_reason="test_design_mapping_changed" if stale else None,
                summary="Mapping changed; reload before confirming." if stale else
                    "Mapping review failed. Verify reviewer access, exact generation pins, every assertion and independent confirmation.")
        await self.events.emit_tool_status(invocation.id, result.status, result.summary, query_keys if result.status == "completed" else [], result)
