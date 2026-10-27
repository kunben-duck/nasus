import asyncio

from ...system_image.structure_cancel_inputs import StructureCancelInput
from ..tool_models import ToolResult
from .query_input import query_payload


class StructureCancellationToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        try:
            self.access.require_invocation_project_scope(invocation)
            request = StructureCancelInput.model_validate({key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_at", "confirmed_by_user"}})
            receipt = await asyncio.to_thread(self.application.cancel, request, invocation_id=invocation.id)
            self.access.require_invocation_project_scope(invocation)
        except Exception:
            summary = "Structural cancellation could not be authorized or verified. Reload the exact original command before confirming again."
            await self.events.emit_tool_status(invocation.id, "failed", summary, [],
                ToolResult(invocation_id=invocation.id, status="failed", summary=summary))
            return
        summary = ("The original structural command has already committed or ended; its facts are retained."
            if receipt.outcome in {"already_committed", "already_terminal"} else
            "Structural command cancelled; no worker can commit a new candidate."
            if receipt.outcome == "cancelled" else
            "Structural cancellation requested. The original command remains running until its worker exits and acknowledges.")
        await self.events.emit_tool_status(invocation.id, "completed", summary,
            [["tool-invocation", request.original_invocation_id], ["system-image-build-plans", request.project_id]],
            ToolResult(invocation_id=invocation.id, status="completed", summary=summary, structure_cancel=receipt))
