import asyncio
from datetime import datetime, timezone

from ...quality_loop.environment_observation_records import EnvironmentRecordQuery
from ...quality_loop.run_plan_environments import RunPlanEnvironmentQuery
from ....domain.quality_loop.environment_observation_record import ENVIRONMENT_RECORD_TOOL
from ..tool_models import ToolResult
from .query_input import query_payload


class EnvironmentObservationRecordToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        keys = []
        await self.events.emit_tool_status(invocation.id, "running", "Verifying original native environment evidence", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            payload = {key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}}
            if invocation.tool_id == ENVIRONMENT_RECORD_TOOL:
                metadata = await asyncio.to_thread(self.application.record, RunPlanEnvironmentQuery.model_validate(payload),
                    invocation_id=invocation.id, recorded_at=datetime.now(timezone.utc).isoformat())
                receipt = {"metadata": metadata, "historical_not_live": True}
                keys = [["run-plan-environments", payload["project_id"]]]
            else:
                query = EnvironmentRecordQuery.model_validate(payload)
                receipt = await asyncio.to_thread(self.application.receipt, query.project_id, query.record_id)
            self.access.require_invocation_project_scope(invocation)
            result = ToolResult(invocation_id=invocation.id, status="completed", run_plan_environment_record=receipt,
                object_refs=["run_plan_environment:" + receipt["metadata"]["record_id"]],
                summary="Original native inventory independently archived and reverified. Historical evidence only; no execution or business coverage authority.")
        except Exception:
            result = ToolResult(invocation_id=invocation.id, status="failed",
                summary="Original environment evidence unavailable. Verify exact saved parents, current source access and independent confirmation. No target request was dispatched.")
        await self.events.emit_tool_status(invocation.id, result.status, result.summary,
            keys if result.status == "completed" else [], result)
