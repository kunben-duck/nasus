import asyncio

from ...quality_loop.run_plan_locators import RunPlanLocatorQuery
from ..tool_models import ToolResult
from .query_input import query_payload


class RunPlanLocatorToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        await self.events.emit_tool_status(invocation.id, "running", "Inspecting fixed-source API locator evidence", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            query = RunPlanLocatorQuery.model_validate(query_payload(invocation.input_payload))
            value = await asyncio.to_thread(self.application.inspect, query)
            self.access.require_invocation_project_scope(invocation)
            result = ToolResult(invocation_id=invocation.id, status="completed", run_plan_locators=value,
                summary="Original actions checked against fixed source declarations. Static evidence only; no HTTP requests, execution permission or business coverage.")
        except Exception:
            result = ToolResult(invocation_id=invocation.id, status="failed",
                summary="Static locator evidence unavailable. Verify the exact saved plan and current source access. No target request was dispatched.")
        await self.events.emit_tool_status(invocation.id, result.status, result.summary, [], result)
