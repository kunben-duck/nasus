import asyncio

from ...system_image.code_index_lifecycle import (
    CODE_INDEX_LIST_TOOL, CODE_INDEX_STATUS_TOOL, CODE_INDEX_CANCEL_TOOL,
    CodeIndexListInput, CodeIndexStatusInput, CodeIndexCancelInput, CodeIndexLifecycleApplicationService,
)
from ....domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from ..errors import PlatformApplicationError
from ..tool_invocation_ports import ToolStatusEventPort
from ..tool_models import ToolInvocation, ToolResult
from .evidence import EvidenceToolAccessPort
from .query_input import query_payload


class CodeIndexLifecycleToolHandler:
    def __init__(self, application: CodeIndexLifecycleApplicationService, events: ToolStatusEventPort, access: EvidenceToolAccessPort):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation: ToolInvocation):
        try:
            self.access.require_invocation_project_scope(invocation)
            payload = query_payload(invocation.input_payload)
            if invocation.tool_id == CODE_INDEX_LIST_TOOL:
                receipt = await asyncio.to_thread(self.application.list, CodeIndexListInput.model_validate(payload))
                summary = "Source-authorized durable generations found; inspect an exact generation before cancellation or recovery."
            elif invocation.tool_id == CODE_INDEX_STATUS_TOOL:
                receipt = await asyncio.to_thread(self.application.read, CodeIndexStatusInput.model_validate(payload))
                summary = "Durable index metadata checked. Worker lease status is not native cache availability or approved business knowledge."
            elif invocation.tool_id == CODE_INDEX_CANCEL_TOOL:
                request = CodeIndexCancelInput.model_validate({key: value for key, value in payload.items()
                    if key not in {"confirmed_by_user", "confirmed_at"}})
                receipt = await asyncio.to_thread(self.application.cancel, request, invocation_id=invocation.id)
                summary = ("The original command already committed or ended; no facts were cancelled."
                    if receipt.outcome in {"already_committed", "already_terminal"}
                    else "Durable cancellation recorded. The worker must acknowledge it; committed facts are retained.")
            else:
                raise ValueError("unsupported code index lifecycle operation")
            self.access.require_invocation_project_scope(invocation)
        except Exception as error:
            summary = ("Code index source access was denied or changed; reload the source."
                if isinstance(error, (SourceAccessDenied, StaleSourceAccessScope, PlatformApplicationError))
                else "Code index lifecycle validation failed; check the exact generation and independent confirmation.")
            await self.events.emit_tool_status(invocation.id, "failed", summary, [],
                ToolResult(invocation_id=invocation.id, status="failed", summary=summary))
            return
        await self.events.emit_tool_status(invocation.id, "completed", summary,
            [["system-image", receipt.request.project_id]] if invocation.tool_id == CODE_INDEX_CANCEL_TOOL else [],
            ToolResult(invocation_id=invocation.id, status="completed", summary=summary, code_index=receipt,
                next_recommended_tools=[CODE_INDEX_STATUS_TOOL] if invocation.tool_id != CODE_INDEX_STATUS_TOOL else []))
