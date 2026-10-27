import asyncio

from ...quality_loop.automation_script_inputs import SCRIPT_PREVIEW_TOOL, SCRIPT_HISTORY_TOOL, ScriptHistoryQuery, ScriptExecutionSelection, ScriptExecutionRequest
from ..tool_models import ToolResult
from .query_input import query_payload


class AutomationScriptToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        await self.events.emit_tool_status(invocation.id, "running", "Verifying fixed automation cases and native budget", [])
        preview, history, refs, keys = None, None, [], []
        try:
            self.access.require_invocation_project_scope(invocation)
            value = {key: item for key, item in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}}
            if invocation.tool_id == SCRIPT_HISTORY_TOOL:
                history = await asyncio.to_thread(self.application.history, ScriptHistoryQuery.model_validate(value))
                summary = "Fixed script history metadata only. Revalidate current source access and page state before use; no execution authority."
            elif invocation.tool_id == SCRIPT_PREVIEW_TOOL:
                preview = await asyncio.to_thread(self.application.preview, ScriptExecutionSelection.model_validate(value))
                summary = "Automation budget preview only. No model call, source egress, target execution or coverage."
            else:
                result = await self.application.execute(ScriptExecutionRequest.model_validate(value), invocation_id=invocation.id)
                refs = ["automation_script_revision:" + result["script_revision_id"]]
                keys = [["automation-script-revisions", value["project_id"]]]
                summary = "Fixed native script draft archived. Independent script review and immutable RunPlan remain required."
            self.access.require_invocation_project_scope(invocation)
            outcome = ToolResult(invocation_id=invocation.id, status="completed", summary=summary,
                object_refs=refs, automation_execution_preview=preview, automation_script_history=history)
        except Exception:
            keys = []
            outcome = ToolResult(invocation_id=invocation.id, status="failed",
                summary="Automation draft unavailable. Recheck current case/oracle pins, source access and confirmed native budget. Unknown calls are never resent.")
        await self.events.emit_tool_status(invocation.id, outcome.status, outcome.summary, keys, outcome)
