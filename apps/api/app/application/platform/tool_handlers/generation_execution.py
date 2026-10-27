import asyncio

from ...quality_loop.generation_execution_inputs import GENERATION_EXECUTION_PREVIEW_TOOL, GENERATION_BATCH_PREVIEW_TOOL, GenerationExecutionSelection
from ...quality_loop.test_design_results import GenerationResultRequest
from ...quality_loop.generation_job_ports import GENERATION_RECOVER_TOOL, GENERATION_CANCEL_TOOL, GENERATION_JOB_QUERY_TOOL, GENERATION_HISTORY_QUERY_TOOL, GenerationJobTarget, parse_generation_recovery, GenerationHistoryRequest
from ..tool_models import ToolResult
from .query_input import query_payload


class GenerationExecutionToolHandler:
    def __init__(self, application, events, access, jobs):
        self.application, self.events, self.access = application, events, access
        self.jobs = jobs

    async def handle(self, invocation):
        await self.events.emit_tool_status(invocation.id, "running", "Verifying complete test-design input and native model budget", [])
        preview, refs = None, []
        try:
            self.access.require_invocation_project_scope(invocation)
            value = {key: item for key, item in query_payload(invocation.input_payload).items() if key not in {"confirmed_by_user", "confirmed_at"}}
            if invocation.tool_id == GENERATION_EXECUTION_PREVIEW_TOOL:
                preview = await asyncio.to_thread(self.application.preview, GenerationExecutionSelection.model_validate(value))
            elif invocation.tool_id == GENERATION_BATCH_PREVIEW_TOOL:
                preview = await asyncio.to_thread(self.application.preview_batches, GenerationExecutionSelection.model_validate(value))
            elif invocation.tool_id == GENERATION_HISTORY_QUERY_TOOL:
                result = await asyncio.to_thread(self.jobs.history, GenerationHistoryRequest.model_validate(value))
                self.access.require_invocation_project_scope(invocation)
                summary = "Bounded generation history inspected; metadata only, no generation or execution authority."
                await self.events.emit_tool_status(invocation.id, "completed", summary, [], ToolResult(
                    invocation_id=invocation.id, status="completed", summary=summary, test_design_jobs=result))
                return
            elif invocation.tool_id == GENERATION_JOB_QUERY_TOOL:
                request = GenerationJobTarget.model_validate(value)
                result = await asyncio.to_thread(self.jobs.read, request.project_id, request.invocation_id)
                summary = "Fixed generation lifecycle inspected; no model request or execution authority."
                await self.events.emit_tool_status(invocation.id, "completed", summary, [], ToolResult(
                    invocation_id=invocation.id, status="completed", summary=summary, test_design_job=result))
                return
            elif invocation.tool_id == GENERATION_CANCEL_TOOL:
                status = await self.jobs.cancel(GenerationJobTarget.model_validate(value), control_id=invocation.id)
                summary = f"Generation is {status}. Committed results and native reservations are retained."
                await self.events.emit_tool_status(invocation.id, "completed", summary, [], ToolResult(
                    invocation_id=invocation.id, status="completed", summary=summary))
                return
            else:
                request = (parse_generation_recovery(value) if invocation.tool_id == GENERATION_RECOVER_TOOL
                    else GenerationResultRequest.model_validate(value))
                try:
                    await self.jobs.dispatch(request, invocation.id)
                except (ValueError, PermissionError):
                    await asyncio.to_thread(self.jobs.repository.finish, request.project_id, invocation.id, "failed",
                        "Generation dispatch rejected. Verify canonical authority and the configured Temporal runtime.")
                except Exception:
                    # A lost dispatch acknowledgement is not a failed operation.
                    # The worker redelivers the canonical intent with the same ID.
                    pass
                return
            self.access.require_invocation_project_scope(invocation)
        except Exception:
            summary = "Generation unavailable. Check current scope, source access, tested model and operator token/pricing policy. Preview and confirm the exact input and budget again. Reserved or unknown provider calls are never resent."
            await self.events.emit_tool_status(invocation.id, "failed", summary, [], ToolResult(invocation_id=invocation.id, status="failed", summary=summary))
            return
        summary = ("Preview only: no source sent. Confirm the fixed destination, source inventory and maximum token/cost reservation."
            if preview else "Draft cases and planned coverage archived. Independent mapping review and target execution remain separate.")
        keys = [] if preview else [["test-design-results", value["project_id"], value["scope_revision_id"]]]
        await self.events.emit_tool_status(invocation.id, "completed", summary, keys, ToolResult(invocation_id=invocation.id,
            status="completed", summary=summary, object_refs=refs, test_design_execution_preview=preview))
