import asyncio

from ...system_image.index_inputs import IndexSelection, IndexBuildRequest, INDEX_PREVIEW_TOOL
from ...system_image.context_retrieval_inputs import ContextRetrievalSelection, CONTEXT_RETRIEVAL_PREVIEW_TOOL
from ..tool_models import ToolResult
from .query_input import query_payload


class FrozenIndexToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        await self.events.emit_tool_status(invocation.id, "running", "Verifying frozen index inputs and model consent", [])
        preview, context_preview, refs = None, None, []
        try:
            self.access.require_invocation_project_scope(invocation)
            if invocation.tool_id == CONTEXT_RETRIEVAL_PREVIEW_TOOL:
                request = ContextRetrievalSelection.model_validate(query_payload(invocation.input_payload))
                context_preview = await asyncio.to_thread(self.application.context_retrieval_preview, request)
            elif invocation.tool_id == INDEX_PREVIEW_TOOL:
                request = IndexSelection.model_validate(query_payload(invocation.input_payload))
                preview = await asyncio.to_thread(self.application.preview, request)
            else:
                request = IndexBuildRequest.model_validate({key: value for key, value in query_payload(invocation.input_payload).items()
                    if key not in {"confirmed_by_user", "confirmed_at"}})
                await self.application.build(request, invocation_id=invocation.id)
                refs = [f"image_index:{invocation.id}"]
            self.access.require_invocation_project_scope(invocation)
        except Exception:
            summary = "Index failed: verify administrator permission, exact publication, source access, current tested embedding model and consent. Reserved partial or uncertain calls cannot be retried automatically. No partial generation is searchable."
            if invocation.tool_id == CONTEXT_RETRIEVAL_PREVIEW_TOOL:
                summary = "Query plan failed: verify administrator permission, exact publication/index, source evidence, current embedding configuration and complete-query budgets. No model call or retrieval was made."
            await self.events.emit_tool_status(invocation.id, "failed", summary, [],
                ToolResult(invocation_id=invocation.id, status="failed", summary=summary))
            return
        summary = ("Preview only, no model call. Confirm the exact source bytes, batch count and destination; retrieval queries will use this pinned model. No rerank export is authorized. Fees are not estimated."
                   if preview else "Immutable retrieval index committed. Semantic recall is not relationship, oracle, coverage or release approval.")
        if context_preview is not None:
            summary = "Query plan only, no model call or retrieval executed. All frozen source ACs and parent descriptions are budgeted against this index and model. Separate confirmation through system_image.context.retrieve starts durable Temporal execution; no relationship, oracle or generation authority."
        await self.events.emit_tool_status(invocation.id, "completed", summary, [],
            ToolResult(invocation_id=invocation.id, status="completed", summary=summary, object_refs=refs,
                index_preview=preview, context_retrieval_preview=context_preview))
