import asyncio
from datetime import datetime, timezone

from ...quality_loop.environment_observation_records import EnvironmentRecordQuery
from ...quality_loop.run_plan_locators import RunPlanLocatorQuery
from ....domain.quality_loop.http_locator_record import LOCATOR_RECORD_TOOL
from ..tool_models import ToolResult
from .query_input import query_payload


class HttpLocatorRecordToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        await self.events.emit_tool_status(invocation.id, "running", "Verifying original fixed source locator evidence", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            payload = {key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}}
            if invocation.tool_id == LOCATOR_RECORD_TOOL:
                metadata = await asyncio.to_thread(self.application.record, RunPlanLocatorQuery.model_validate(payload),
                    invocation_id=invocation.id, recorded_at=datetime.now(timezone.utc).isoformat())
                receipt = {"metadata": metadata, "historical_not_live": True}
            else:
                query = EnvironmentRecordQuery.model_validate(payload)
                receipt = await asyncio.to_thread(self.application.receipt, query.project_id, query.record_id)
            self.access.require_invocation_project_scope(invocation)
            result = ToolResult(invocation_id=invocation.id, status="completed", run_plan_locator_record=receipt,
                object_refs=["run_plan_locators:" + receipt["metadata"]["record_id"]],
                summary="Original static source locators independently archived. No runtime, execution or business coverage authority.")
        except Exception:
            result = ToolResult(invocation_id=invocation.id, status="failed",
                summary="Original locator evidence unavailable. Verify saved plan, source access and independent confirmation. No execution or coverage recorded.")
        keys = [["run-plan-locators", payload["project_id"]]] if result.status == "completed" and invocation.tool_id == LOCATOR_RECORD_TOOL else []
        await self.events.emit_tool_status(invocation.id, result.status, result.summary, keys, result)
