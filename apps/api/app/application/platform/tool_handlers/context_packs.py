import asyncio
from datetime import datetime, timezone

from ...system_image.context_pack_inputs import ContextPreviewInput, ContextCompileInput, ContextReadInput, ContextListInput, ContextAuthorityRegistrationInput, ContextAuthorityBackfillInput, CONTEXT_AUTHORITY_BACKFILL_TOOL
from ....domain.system_image.context_authorities import REGISTER_CONTEXT_AUTHORITIES_TOOL, ContextAuthorityRegistrationRequired
from ....domain.system_image.context_pack import COMPILE_CONTEXT_TOOL, ContextPackChanged, MandatoryContextTooLarge
from ..tool_models import ToolResult
from .query_input import query_payload


CONTEXT_PREVIEW_TOOL = "query.system_image.context.preview"
CONTEXT_READ_TOOL = "query.system_image.context.read"
CONTEXT_LIST_TOOL = "query.system_image.context.list"
CONTEXT_QUERY_INPUTS = {CONTEXT_PREVIEW_TOOL: ContextPreviewInput, CONTEXT_READ_TOOL: ContextReadInput,
    CONTEXT_LIST_TOOL: ContextListInput, CONTEXT_AUTHORITY_BACKFILL_TOOL: ContextAuthorityBackfillInput}


class ContextPackToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        await self.events.emit_tool_status(invocation.id, "running", "Verifying pinned context, mandatory requirements and source access", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            payload = {k: v for k, v in query_payload(invocation.input_payload).items() if k not in {"confirmed_by_user", "confirmed_at"}}
            if invocation.tool_id == REGISTER_CONTEXT_AUTHORITIES_TOOL:
                request = ContextAuthorityRegistrationInput.model_validate(payload)
                value = await asyncio.to_thread(self.application.register_authorities, request, invocation_id=invocation.id,
                    recorded_at=datetime.now(timezone.utc).isoformat())
                result = ToolResult(invocation_id=invocation.id, status="completed",
                    summary="Exact historical authority dependencies registered from the verified original archive. No approval, source text, current head or execution permission was changed.",
                    object_refs=["context_pack:" + value["context_id"]], next_recommended_tools=[CONTEXT_READ_TOOL])
            elif invocation.tool_id == COMPILE_CONTEXT_TOOL:
                request = ContextCompileInput.model_validate(payload)
                value = await asyncio.to_thread(self.application.compile, request, invocation_id=invocation.id,
                    recorded_at=datetime.now(timezone.utc).isoformat())
                result = ToolResult(invocation_id=invocation.id, status="completed",
                    summary="Draft test-design context archived with mandatory constraints and explicit gaps. Not authorization to generate, execute or release.",
                    object_refs=[f"context_pack:{value['context_id']}"], next_recommended_tools=[CONTEXT_READ_TOOL])
            else:
                request = CONTEXT_QUERY_INPUTS[invocation.tool_id].model_validate(payload)
                receipt = await asyncio.to_thread(self.application.receipt, request)
                if invocation.tool_id == CONTEXT_AUTHORITY_BACKFILL_TOOL:
                    result = ToolResult(invocation_id=invocation.id, status="completed", context_authority_backfill=receipt,
                        summary="Original historical contexts needing dependency registration discovered. Revalidate this bounded metadata page and confirm each registration independently; no approval or execution authority granted.",
                        next_recommended_tools=[REGISTER_CONTEXT_AUTHORITIES_TOOL] if receipt.items else [])
                else:
                    result = ToolResult(invocation_id=invocation.id, status="completed", context_pack=receipt,
                        summary="Context metadata inspected. Source text is not embedded in this receipt; mandatory gaps are not generation authorization.")
            self.access.require_invocation_project_scope(invocation)
        except Exception as exc:
            reason = "context_authority_registration_required" if isinstance(exc, ContextAuthorityRegistrationRequired) else "context_inputs_changed" if isinstance(exc, ContextPackChanged) else "mandatory_context_over_budget" if isinstance(exc, MandatoryContextTooLarge) else "context_verification_failed"
            summary = {"context_authority_registration_required": "Original historical context dependencies require independent confirmed registration before use.",
                "context_inputs_changed": "Context inputs changed. Preview and confirm again.",
                "mandatory_context_over_budget": "Mandatory context exceeds budget. Split scope or increase the budget; no requirement was discarded."}.get(reason,
                "Context could not be verified. Check the source access, fixed revision and confirmation.")
            result = ToolResult(invocation_id=invocation.id, status="failed", summary=summary,
                requires_followup=True, followup_reason=reason,
                next_recommended_tools=[CONTEXT_AUTHORITY_BACKFILL_TOOL] if isinstance(exc, ContextAuthorityRegistrationRequired) else [CONTEXT_PREVIEW_TOOL])
        await self.events.emit_tool_status(invocation.id, result.status, result.summary, [], result)
