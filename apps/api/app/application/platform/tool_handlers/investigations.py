import asyncio
from datetime import datetime, timezone

from ...system_image.investigations import (INVESTIGATE_TOOL, INVESTIGATION_READ_TOOL,
    InvestigationInput, InvestigationReadInput, InvestigationReceipt)
from ..actor_context import current_user
from ..tool_models import ToolResult
from .query_input import query_payload


class InvestigationToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        try:
            self.access.require_invocation_project_scope(invocation)
            body = query_payload(invocation.input_payload)
            if invocation.tool_id == INVESTIGATE_TOOL:
                body = {key: value for key, value in body.items() if key not in {"confirmed_at", "confirmed_by_user"}}
                request = InvestigationInput.model_validate(body)
                actor = current_user()
                stored = await asyncio.to_thread(self.application.create, request, invocation_id=invocation.id,
                    actor_id=actor.id, created_at=datetime.now(timezone.utc).isoformat())
            else:
                request = InvestigationReadInput.model_validate(body)
                stored = await asyncio.to_thread(self.application.read, request.project_id, request.revision_id)
            self.access.require_invocation_project_scope(invocation)
        except Exception:
            summary = "Investigation could not be verified; reread its fixed goal, parent, candidate and current source access."
            await self.events.emit_tool_status(invocation.id, "failed", summary, [], ToolResult(
                invocation_id=invocation.id, status="failed", summary=summary))
            return
        summary = "Evidence-driven investigation revision verified. Proposed follow-up tasks require separate authorization; no business approval or publication was granted."
        await self.events.emit_tool_status(invocation.id, "completed", summary, [], ToolResult(
            invocation_id=invocation.id, status="completed", summary=summary,
            object_refs=[f"image_investigation:{stored.revision_id}"],
            investigation=InvestigationReceipt(project_id=stored.request.project_id,
                revision_id=stored.revision_id, revision_hash=stored.revision_hash),
            next_recommended_tools=[INVESTIGATION_READ_TOOL] if invocation.tool_id == INVESTIGATE_TOOL else []))
