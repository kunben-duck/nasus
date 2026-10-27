from __future__ import annotations

import asyncio
from typing import Protocol

from pydantic import ValidationError

from ....domain.system_image.evidence import (
    EvidenceIntegrityError, EvidenceLocationUnavailable, EvidencePageTooLarge, EvidenceUnavailableError,
)
from ...system_image.evidence_tool_models import EvidenceListInput, EvidenceReadInput, EvidenceListReceipt
from ...system_image.evidence_tools import EvidenceToolPort
from ..errors import PlatformApplicationError
from ..tool_invocation_ports import ToolStatusEventPort
from ..tool_models import ToolInvocation, ToolResult
from .query_input import query_payload


LIST_EVIDENCE_TOOL = "query.system_image.evidence.list"
READ_EVIDENCE_TOOL = "query.system_image.evidence.read"


class EvidenceToolAccessPort(Protocol):
    def require_invocation_project_scope(self, invocation: ToolInvocation) -> None: ...


class EvidenceToolHandler:
    def __init__(self, evidence: EvidenceToolPort, events: ToolStatusEventPort, access: EvidenceToolAccessPort) -> None:
        self.evidence = evidence
        self.events = events
        self.access = access

    async def handle(self, invocation: ToolInvocation) -> None:
        await self.events.emit_tool_status(invocation.id, "running", "Checking pinned source evidence", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            payload = query_payload(invocation.input_payload)
            if invocation.tool_id == LIST_EVIDENCE_TOOL:
                receipt = await asyncio.to_thread(self.evidence.list, EvidenceListInput.model_validate(payload))
            elif invocation.tool_id == READ_EVIDENCE_TOOL:
                receipt = await asyncio.to_thread(self.evidence.read, EvidenceReadInput.model_validate(payload))
            else:
                raise ValueError("unsupported evidence operation")
            self.access.require_invocation_project_scope(invocation)
        except Exception as exc:
            # Exception messages can contain provider/object-store data; never persist them.
            summary = self._failure_summary(exc)
            await self.events.emit_tool_status(invocation.id, "failed", summary, [], ToolResult(
                invocation_id=invocation.id, status="failed", summary=summary,
            ))
            return

        if isinstance(receipt, EvidenceListReceipt):
            refs = [item.evidence_id for item in receipt.items]
            summary = f"Found {len(refs)} evidence references at source revision {receipt.source_revision_id}."
            next_tools = [READ_EVIDENCE_TOOL] if refs else []
        else:
            refs = [receipt.evidence.evidence_id]
            summary = f"Verified source evidence lines {receipt.start_line}-{receipt.end_line}; source text is available through authorized expansion."
            next_tools = [READ_EVIDENCE_TOOL] if receipt.next_start_line else []
        await self.events.emit_tool_status(invocation.id, "completed", summary, [], ToolResult(
            invocation_id=invocation.id, status="completed", summary=summary,
            evidence_refs=refs, evidence_query=receipt, next_recommended_tools=next_tools,
        ))

    @staticmethod
    def _failure_summary(exc: Exception) -> str:
        if isinstance(exc, PlatformApplicationError):
            return "Source evidence access was denied."
        if isinstance(exc, KeyError):
            return "Source evidence was not found at the requested project/revision."
        if isinstance(exc, EvidenceLocationUnavailable):
            return "Source evidence has no exact location; an exact read cannot be verified."
        if isinstance(exc, EvidencePageTooLarge):
            return "Source evidence exceeds the query limit; request fewer lines."
        if isinstance(exc, EvidenceIntegrityError):
            return "Source evidence failed integrity verification."
        if isinstance(exc, EvidenceUnavailableError):
            return "Source evidence is temporarily unavailable."
        if isinstance(exc, (ValidationError, ValueError)):
            return "Invalid source evidence query; explicit project/revision pins and valid page bounds are required."
        return "Source evidence query failed."
