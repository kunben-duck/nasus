import asyncio
from datetime import datetime, timezone

from ...quality_loop.mapping_part_inputs import MappingPartStageInput
from ....domain.quality_loop.test_design_mapping import TestDesignMappingChanged, MAPPING_QUERY_TOOL
from ..tool_models import ToolResult
from .query_input import query_payload


class MappingPartStagingToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        await self.events.emit_tool_status(invocation.id, "running", "Verifying exact review partition", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            request = MappingPartStageInput.model_validate({key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_at", "confirmed_by_user"}})
            value = await asyncio.to_thread(self.application.stage, request, invocation_id=invocation.id,
                recorded_at=datetime.now(timezone.utc).isoformat())
            self.access.require_invocation_project_scope(invocation)
            result = ToolResult(invocation_id=invocation.id, status="completed",
                summary="Private review part saved. It does not approve mappings or grant execution.",
                object_refs=["test_design_mapping_part:" + value["part_revision_id"]], next_recommended_tools=[MAPPING_QUERY_TOOL])
        except Exception as exc:
            changed = isinstance(exc, TestDesignMappingChanged)
            result = ToolResult(invocation_id=invocation.id, status="failed", requires_followup=changed,
                followup_reason="test_design_mapping_changed" if changed else None,
                summary="Mapping or part changed; inspect again before confirming." if changed else
                    "Part save failed. Verify current reviewer/source access, exact pins and independent confirmation.")
        await self.events.emit_tool_status(invocation.id, result.status, result.summary, [], result)
