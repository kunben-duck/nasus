import asyncio

from ...system_image.semantic_evaluations import SemanticSelection, SemanticEvaluationRequest, SEMANTIC_PREVIEW_TOOL
from ..tool_models import ToolResult
from .query_input import query_payload


class SemanticEvaluationToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        await self.events.emit_tool_status(invocation.id, "running", "Verifying source-pinned semantic evaluation consent", [])
        preview = None
        try:
            self.access.require_invocation_project_scope(invocation)
            if invocation.tool_id == SEMANTIC_PREVIEW_TOOL:
                request = SemanticSelection.model_validate(query_payload(invocation.input_payload))
                preview = await asyncio.to_thread(self.application.preview, request)
                refs = []
            else:
                request = SemanticEvaluationRequest.model_validate({key: value for key, value in query_payload(invocation.input_payload).items()
                    if key not in {"confirmed_at", "confirmed_by_user"}})
                await self.application.evaluate(request, invocation_id=invocation.id)
                refs = [f"semantic_evaluation:{invocation.id}"]
            self.access.require_invocation_project_scope(invocation)
        except Exception:
            summary = "Semantic evaluation failed. Check administrator permission, consent pins, source access, historical review screening and the tested live model. Same-revision rejection requires human re-review. Changed review heads require a new preview. Reserved calls are not retried automatically."
            await self.events.emit_tool_status(invocation.id, "failed", summary, [], ToolResult(invocation_id=invocation.id, status="failed", summary=summary))
            return
        summary = ("Preview only: no source was sent. Confirm the exact destination, source scope and one-call budget before model egress. Provider charges are not estimated."
                   if preview else "Proposed semantic evaluation archived. This does not approve a relation, oracle or verified coverage.")
        await self.events.emit_tool_status(invocation.id, "completed", summary, [], ToolResult(invocation_id=invocation.id,
            status="completed", summary=summary, object_refs=refs, semantic_preview=preview))
