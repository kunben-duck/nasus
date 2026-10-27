import asyncio

from pydantic import BaseModel, ConfigDict, Field

from ...system_image.context_retrieval_ports import CONTEXT_RETRIEVE_TOOL, CONTEXT_RETRIEVAL_QUERY_TOOL, ContextRetrievalRequest
from ..tool_models import ToolResult
from .query_input import query_payload


class CancelContextRetrieval(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    project_id: str = Field(min_length=1, max_length=128)
    invocation_id: str = Field(min_length=1, max_length=128)


class ContextRetrievalToolHandler:
    def __init__(self, jobs, events, access):
        self.jobs, self.events, self.access = jobs, events, access

    async def handle(self, invocation):
        self.access.require_invocation_project_scope(invocation)
        payload = {key: value for key, value in query_payload(invocation.input_payload).items()
            if key not in {"confirmed_at", "confirmed_by_user"}}
        if invocation.tool_id == CONTEXT_RETRIEVE_TOOL:
            request = ContextRetrievalRequest.model_validate(payload)
            await self.events.emit_tool_status(invocation.id, "running", "Confirmed context retrieval queued for durable execution", [])
            try:
                await self.jobs.dispatch(request, invocation.id)
            except (ValueError, PermissionError):
                await asyncio.to_thread(self.jobs.repository.finish, request.project_id, invocation.id, "failed",
                    "Context retrieval dispatch rejected. Verify administrator access and a configured Temporal runtime.")
            except Exception:
                # Dispatch may have succeeded before the acknowledgement was lost.
                # A worker reconciles this durable intent using the same workflow ID.
                pass
            return
        request = CancelContextRetrieval.model_validate(payload)
        if invocation.tool_id == CONTEXT_RETRIEVAL_QUERY_TOOL:
            result = await asyncio.to_thread(self.jobs.application.read, request.project_id, request.invocation_id)
            await asyncio.to_thread(self.jobs.application.indexes.require_replay_current, request.project_id, result)
            summary = "Complete fixed AC retrieval mapping revalidated. Not relationship, oracle, coverage or generation approval."
            await self.events.emit_tool_status(invocation.id, "completed", summary, [], ToolResult(
                invocation_id=invocation.id, status="completed", summary=summary, context_retrieval_result=result))
            return
        status = await self.jobs.cancel(request.project_id, request.invocation_id)
        summary = f"Context retrieval is {status}. Committed results cannot be overwritten by cancellation."
        await self.events.emit_tool_status(invocation.id, "completed", summary, [], ToolResult(
            invocation_id=invocation.id, status="completed", summary=summary))
