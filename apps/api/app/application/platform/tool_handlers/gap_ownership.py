import asyncio
from datetime import datetime, timezone

from ...system_image.gap_ownership import GapOwnershipInput
from ..actor_context import current_user
from ..tool_models import ToolResult
from .query_input import query_payload


class GapOwnershipToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        try:
            self.access.require_invocation_project_scope(invocation)
            body = query_payload(invocation.input_payload)
            body.pop("confirmed_at", None)
            body.pop("confirmed_by_user", None)
            request = GapOwnershipInput.model_validate(body)
            stored = await asyncio.to_thread(self.application.create, request, invocation_id=invocation.id,
                actor_id=current_user().id, created_at=datetime.now(timezone.utc).isoformat())
            self.access.require_invocation_project_scope(invocation)
        except Exception:
            summary = "Gap responsibilities could not be verified. Reload the original report, checkpoint, current owners and predecessor; no gap was resolved."
            await self.events.emit_tool_status(invocation.id, "failed", summary, [], ToolResult(
                invocation_id=invocation.id, status="failed", summary=summary))
            return
        summary = "Responsibilities for fixed build gaps were confirmed. The original report and goal remain unchanged; no gap resolution, execution or publication was authorized."
        await self.events.emit_tool_status(invocation.id, "completed", summary, [], ToolResult(invocation_id=invocation.id,
            status="completed", summary=summary, object_refs=[f"build_gap_ownership:{stored.revision_id}"],
            build_gap_ownership=self.application.receipt(stored)))
