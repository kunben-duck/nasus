import asyncio
from datetime import datetime, timezone

from ...quality_loop.run_plan_inputs import RunPlanSelection, RunPlanRequest
from ....domain.quality_loop.run_plan import RUN_PLAN_TOOL, RunPlanChanged
from ..tool_models import ToolResult
from .query_input import query_payload


class RunPlanToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        keys = []
        await self.events.emit_tool_status(invocation.id, "running", "Verifying fixed reviewed inputs and target declarations", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            value = {key: item for key, item in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}}
            if invocation.tool_id == RUN_PLAN_TOOL:
                metadata = await asyncio.to_thread(self.application.prepare, RunPlanRequest.model_validate(value),
                    invocation_id=invocation.id, recorded_at=datetime.now(timezone.utc).isoformat())
                result = ToolResult(invocation_id=invocation.id, status="completed",
                    summary="Immutable RunPlan prepared. Build/environment/fixtures are declarations, not verified execution or coverage.",
                    object_refs=["run_plan:" + metadata["run_plan_id"]])
                keys = [["run-plans", value["project_id"]]]
            else:
                preview = await asyncio.to_thread(self.application.preview, RunPlanSelection.model_validate(value))
                result = ToolResult(invocation_id=invocation.id, status="completed", run_plan_preview=preview,
                    summary="RunPlan preview only. Confirm preparation separately; no model, build or target execution.")
            self.access.require_invocation_project_scope(invocation)
        except Exception as exc:
            stale = isinstance(exc, RunPlanChanged)
            result = ToolResult(invocation_id=invocation.id, status="failed", requires_followup=stale,
                followup_reason="run_plan_changed" if stale else None,
                summary="RunPlan inputs changed; preview and confirm again." if stale else
                    "RunPlan unavailable. Verify original reviewed inputs, target declarations, source access and fresh confirmation.")
        await self.events.emit_tool_status(invocation.id, result.status, result.summary,
            keys if result.status == "completed" else [], result)
