import asyncio

from ...quality_loop.test_design_generation import GenerationSelection
from ..tool_models import ToolResult
from .query_input import query_payload


class TestDesignGenerationQueryHandler:
    __test__ = False

    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        await self.events.emit_tool_status(invocation.id, "running", "Checking fixed generation obligations", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            request = GenerationSelection.model_validate(query_payload(invocation.input_payload))
            receipt = await asyncio.to_thread(self.application.receipt, request)
            self.access.require_invocation_project_scope(invocation)
            result = ToolResult(invocation_id=invocation.id, status="completed", test_design_generation=receipt,
                summary="Fixed generation obligations inspected. Model, budget and commit gates remain separate; no cases were generated.")
        except Exception:
            result = ToolResult(invocation_id=invocation.id, status="failed",
                summary="Generation input unavailable. Check source access, current scope pins and unresolved obligations.")
        await self.events.emit_tool_status(invocation.id, result.status, result.summary, [], result)
