import asyncio

from ...quality_loop.native_build_inputs import (
    NATIVE_BUILD_TOOL, NATIVE_BUILD_PREVIEW_TOOL, NATIVE_BUILD_QUERY_TOOL,
    NativeBuildCommand, NativeBuildSelection, NativeBuildTarget,
)
from ..tool_models import ToolResult
from .query_input import query_payload


class NativeBuildToolHandler:
    def __init__(self, application, jobs, events, access):
        self.application, self.jobs, self.events, self.access = application, jobs, events, access

    async def handle(self, invocation):
        await self.events.emit_tool_status(invocation.id, "running", "Verifying exact native build inputs and authority", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            value = {k: v for k, v in query_payload(invocation.input_payload).items() if k not in {"confirmed_at", "confirmed_by_user"}}
            if invocation.tool_id == NATIVE_BUILD_TOOL:
                request = NativeBuildCommand.model_validate(value)
                try:
                    await self.jobs.dispatch(request, invocation.id)
                except (ValueError, PermissionError):
                    await asyncio.to_thread(self.jobs.repository.finish, request.project_id, invocation.id, "failed")
                except Exception:
                    # Unknown dispatch acknowledgement is redelivered under the
                    # same workflow ID, never treated as a new native attempt.
                    pass
                return
            if invocation.tool_id == NATIVE_BUILD_PREVIEW_TOOL:
                result = await asyncio.to_thread(self.application.preview, NativeBuildSelection.model_validate(value))
                field, summary = "native_build_preview", "Preview only. Independently confirm the exact source execution; no target test execution authority."
            elif invocation.tool_id == NATIVE_BUILD_QUERY_TOOL:
                target = NativeBuildTarget.model_validate(value)
                view = await asyncio.to_thread(self.application.read, target.project_id, target.invocation_id)
                result = {key: item for key, item in view.items() if key != "receipt"}
                field, summary = "native_build_job", "Original native build inspected under current source access; no rebuild or target execution."
            else:
                target = NativeBuildTarget.model_validate(value)
                status = await self.jobs.cancel(target, control_id=invocation.id)
                field, result = "native_build_job", {"project_id": target.project_id, "invocation_id": target.invocation_id,
                    "status": status, "cancellation_requested": status == "cancelled",
                    "cleanup_confirmed": False, "execution_authorized": False}
                summary = "Build cancellation recorded. Committed artifacts are retained; no new execution authority."
            self.access.require_invocation_project_scope(invocation)
            await self.events.emit_tool_status(invocation.id, "completed", summary, [], ToolResult(
                invocation_id=invocation.id, status="completed", summary=summary, **{field: result}))
        except Exception:
            summary = "Native build unavailable. Check current administrator/source access, fixed pins, fresh confirmation and operator runtime. Reserved attempts are never automatically rebuilt."
            await self.events.emit_tool_status(invocation.id, "failed", summary, [], ToolResult(
                invocation_id=invocation.id, status="failed", summary=summary))
