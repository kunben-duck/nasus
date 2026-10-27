import asyncio

from ...quality_loop.run_plan_environments import RunPlanEnvironmentQuery
from ..tool_models import ToolResult
from .query_input import query_payload


class RunPlanEnvironmentToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        await self.events.emit_tool_status(invocation.id, "running", "Inspecting the original owned target and mounted artifact", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            query = RunPlanEnvironmentQuery.model_validate(query_payload(invocation.input_payload))
            receipt = await asyncio.to_thread(self.application.inspect, query)
            self.access.require_invocation_project_scope(invocation)
            result = ToolResult(invocation_id=invocation.id, status="completed", run_plan_environment=receipt,
                summary="Original target artifact and selected configuration observed. Historical snapshot only; no execution, fixture or business coverage authority.")
        except Exception:
            result = ToolResult(invocation_id=invocation.id, status="failed",
                summary="Target inspection unavailable. Verify the exact saved plan/build, current source access and operator-owned environment policy. No target request was dispatched.")
        await self.events.emit_tool_status(invocation.id, result.status, result.summary, [], result)
