from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from ...system_image.reference_links import ReferenceLinkApplicationService, ReferenceProposalInput
from ..tool_invocation_ports import ToolStatusEventPort
from ..tool_models import ToolInvocation, ToolResult
from .evidence import EvidenceToolAccessPort
from .query_input import query_payload


class ReferenceLinkToolHandler:
    def __init__(self, application: ReferenceLinkApplicationService, events: ToolStatusEventPort, access: EvidenceToolAccessPort):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation: ToolInvocation) -> None:
        await self.events.emit_tool_status(invocation.id, "running", "Checking explicit references against frozen source evidence", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            request = ReferenceProposalInput.model_validate(query_payload(invocation.input_payload))
            saved = await asyncio.to_thread(self.application.propose, request, invocation_id=invocation.id,
                                           created_at=datetime.now(timezone.utc).isoformat())
            self.access.require_invocation_project_scope(invocation)
        except Exception:
            summary = "Reference derivation failed. Check the fixed image, source access, evidence and input limits."
            await self.events.emit_tool_status(invocation.id, "failed", summary, [], ToolResult(
                invocation_id=invocation.id, status="failed", summary=summary))
            return
        summary = "Explicit reference candidates saved. References are not implementation, test coverage, approved requirements or publication."
        await self.events.emit_tool_status(invocation.id, "completed", summary, [], ToolResult(
            invocation_id=invocation.id, status="completed", summary=summary,
            object_refs=[f"image_reference_proposal:{saved.proposal_id}"], requires_followup=True,
            followup_reason="reference_candidate_review", followup_prompt="Inspect the source-pinned references and unresolved gaps.",
            next_recommended_tools=["query.system_image.references.read"]))
