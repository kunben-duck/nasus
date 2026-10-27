import asyncio
from datetime import datetime, timezone

from ...quality_loop.run_plan_build_inputs import RunPlanBuildSelection, RunPlanBuildRequest, RunPlanBuildQuery
from ....domain.quality_loop.run_plan import RunPlanChanged
from ....domain.quality_loop.run_plan_build import RUN_PLAN_BUILD_TOOL, RUN_PLAN_BUILD_PREVIEW_TOOL
from ..tool_models import ToolResult
from .query_input import query_payload


class RunPlanBuildToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        keys = []
        await self.events.emit_tool_status(invocation.id, "running", "Verifying original RunPlan and complete native build scope", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            value = {key: item for key, item in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}}
            if invocation.tool_id == RUN_PLAN_BUILD_TOOL:
                metadata = await asyncio.to_thread(self.application.bind, RunPlanBuildRequest.model_validate(value),
                    invocation_id=invocation.id, recorded_at=datetime.now(timezone.utc).isoformat())
                result = ToolResult(invocation_id=invocation.id, status="completed",
                    summary="Original build and complete source scope bound. Environment, fixtures and execution require independent verification.",
                    object_refs=["run_plan_build:" + metadata["binding_id"]])
                keys = [["run-plan-builds", value["project_id"]]]
            elif invocation.tool_id == RUN_PLAN_BUILD_PREVIEW_TOOL:
                receipt = await asyncio.to_thread(self.application.preview, RunPlanBuildSelection.model_validate(value))
                result = ToolResult(invocation_id=invocation.id, status="completed", run_plan_build_preview=receipt,
                    summary="Original build binding preview. No build, model, target execution or passed coverage.")
            else:
                query = RunPlanBuildQuery.model_validate(value)
                receipt = await asyncio.to_thread(self.application.receipt, query.project_id, query.binding_id)
                result = ToolResult(invocation_id=invocation.id, status="completed", run_plan_build=receipt,
                    summary="Original build binding reauthorized. Attestation is not execution permission or passed coverage.")
            self.access.require_invocation_project_scope(invocation)
        except Exception as exc:
            stale = isinstance(exc, RunPlanChanged)
            result = ToolResult(invocation_id=invocation.id, status="failed", requires_followup=stale,
                followup_reason="run_plan_build_changed" if stale else None,
                summary="RunPlan build inputs changed; preview and confirm again." if stale else
                    "Build binding unavailable. Verify original plan, every source/build, exact hashes, source access and fresh confirmation.")
        await self.events.emit_tool_status(invocation.id, result.status, result.summary,
            keys if result.status == "completed" else [], result)
