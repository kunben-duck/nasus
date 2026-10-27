import logging

from ...quality_loop.run_plan_case_inputs import RunPlanCaseExecutionSelection
from ...quality_loop.run_plan_case_jobs import RunPlanCaseJobTarget
from ...quality_loop.worker_threads import run_worker_thread
from ....domain.quality_loop.run_plan_case_execution import CASE_EXECUTE_TOOL, CASE_CANCEL_TOOL
from ....domain.quality_loop.run_plan_case_job import CASE_JOB_QUERY_TOOL
from ..tool_models import ToolResult
from .query_input import query_payload

logger = logging.getLogger(__name__)


class RunPlanCaseJobToolHandler:
    def __init__(self, jobs, events, access):
        self.jobs, self.events, self.access = jobs, events, access

    async def handle(self, invocation):
        if invocation.tool_id == CASE_EXECUTE_TOOL:
            try:
                self.access.require_invocation_project_scope(invocation)
                request = RunPlanCaseExecutionSelection.model_validate(self._payload(invocation))
                await self.jobs.dispatch(request, invocation.id)
            except (ValueError, KeyError, PermissionError):
                try:
                    await self.jobs.fail(invocation.id)
                except Exception:
                    logger.warning("Original case termination deferred until its command and worker can be fenced")
            except Exception:
                logger.warning("Original case dispatch acknowledgement deferred for same-ID reconciliation")
            return
        try:
            self.access.require_invocation_project_scope(invocation)
            target = RunPlanCaseJobTarget.model_validate(self._payload(invocation))
            if invocation.tool_id == CASE_JOB_QUERY_TOOL:
                metadata = await run_worker_thread(lambda: self.jobs.metadata(target))
                summary = "Original case lifecycle inspected; partial and unknown output does not grant business coverage or retry."
            elif invocation.tool_id == CASE_CANCEL_TOOL:
                await self.jobs.cancel(target, control_id=invocation.id)
                metadata = None
                summary = "Original case cancellation recorded or inspected; no target rollback, cleanup or unknown-effect retry."
            else:
                raise ValueError("unsupported original case lifecycle command")
            self.access.require_invocation_project_scope(invocation)
            result = ToolResult(invocation_id=invocation.id, status="completed", summary=summary, run_plan_case_job=metadata)
        except Exception:
            result = ToolResult(invocation_id=invocation.id, status="failed",
                summary="Original case lifecycle unavailable. Verify administrator/source access and independent confirmation; unknown effects are not resent.")
        await self.events.emit_tool_status(invocation.id, result.status, result.summary, [], result)

    @staticmethod
    def _payload(invocation):
        return {key: item for key, item in query_payload(invocation.input_payload).items()
            if key not in {"confirmed_by_user", "confirmed_at"}}
