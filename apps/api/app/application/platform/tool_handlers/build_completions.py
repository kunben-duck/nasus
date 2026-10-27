import asyncio

from ...system_image.build_completions import BuildCompletionInput
from ..tool_models import ToolResult
from .query_input import query_payload


class BuildCompletionToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        try:
            self.access.require_invocation_project_scope(invocation)
            request = BuildCompletionInput.model_validate(query_payload(invocation.input_payload))
            report = await asyncio.to_thread(self.application.read, request)
            receipt = self.application.receipt(request, report)
            self.access.require_invocation_project_scope(invocation)
        except Exception:
            summary = "Completion assessment could not be verified. Reload its fixed investigation, goal checkpoint and source access."
            await self.events.emit_tool_status(invocation.id, "failed", summary, [], ToolResult(
                invocation_id=invocation.id, status="failed", summary=summary))
            return
        summary = "Candidate completion assessment is fixed. Delivery remains blocked by unverified readiness, cumulative budget and unresolved gaps; no goal completion or publication was granted."
        await self.events.emit_tool_status(invocation.id, "completed", summary, [], ToolResult(
            invocation_id=invocation.id, status="completed", summary=summary,
            object_refs=[f"build_completion:{invocation.id}"], build_completion=receipt))
