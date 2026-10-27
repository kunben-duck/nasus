import asyncio
from datetime import datetime, timezone

from ...quality_loop.run_plan_observation_records import (
    ObservationRecordRequest, ObservationRecordQuery, OBSERVATION_RECORD_TOOL,
)
from ..tool_models import ToolResult
from .query_input import query_payload


class RunPlanObservationRecordToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        keys = []
        await self.events.emit_tool_status(invocation.id, "running", "Verifying original response evidence and complete case roster", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            value = {key: item for key, item in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}}
            if invocation.tool_id == OBSERVATION_RECORD_TOOL:
                metadata = await asyncio.to_thread(self.application.record, ObservationRecordRequest.model_validate(value),
                    invocation_id=invocation.id, recorded_at=datetime.now(timezone.utc).isoformat())
                result = ToolResult(invocation_id=invocation.id, status="completed",
                    summary="Original observations recorded. This does not authorize execution or establish business coverage.",
                    object_refs=["run_plan_observations:" + metadata["record_id"]])
                keys = [["run-plan-observations", value["project_id"]]]
            else:
                query = ObservationRecordQuery.model_validate(value)
                receipt = await asyncio.to_thread(self.application.receipt, query.project_id, query.record_id)
                result = ToolResult(invocation_id=invocation.id, status="completed", run_plan_observations=receipt,
                    summary="Original observations reauthorized. Unknown outcomes are not business failures or verified coverage.")
            self.access.require_invocation_project_scope(invocation)
        except Exception:
            result = ToolResult(invocation_id=invocation.id, status="failed",
                summary="Original observations unavailable. Verify exact parent, response archive, source access and independent confirmation.")
        await self.events.emit_tool_status(invocation.id, result.status, result.summary,
            keys if result.status == "completed" else [], result)
