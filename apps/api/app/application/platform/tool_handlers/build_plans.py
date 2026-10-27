from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from ...system_image.build_plans import BuildPlanApplicationService, BuildPlanInput
from ...system_image.build_plan_queries import BuildPlanQueryApplicationService, BuildPlanReadInput, READ_BUILD_PLAN_TOOL
from ....domain.system_image.build_plan import BuildPlanIntegrityError
from ....domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from ..tool_invocation_ports import ToolStatusEventPort
from ..tool_models import ToolInvocation, ToolResult
from .evidence import EvidenceToolAccessPort, EvidenceToolHandler
from .query_input import query_payload


class BuildPlanToolHandler:
    def __init__(self, plans: BuildPlanApplicationService, events: ToolStatusEventPort, access: EvidenceToolAccessPort):
        self.plans, self.events, self.access = plans, events, access

    async def handle(self, invocation: ToolInvocation) -> None:
        await self.events.emit_tool_status(invocation.id, "running", "Preparing source-pinned investigation plan", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            request = BuildPlanInput.model_validate(query_payload(invocation.input_payload))
            record = await asyncio.to_thread(self.plans.create, request, invocation_id=invocation.id,
                                            created_at=datetime.now(timezone.utc).isoformat())
            self.access.require_invocation_project_scope(invocation)
        except Exception as exc:
            if isinstance(exc, (SourceAccessDenied, StaleSourceAccessScope)):
                summary = "Build input access was denied or changed; reload the sources."
            elif isinstance(exc, BuildPlanIntegrityError):
                summary = "Build plan failed integrity verification."
            else:
                summary = EvidenceToolHandler._failure_summary(exc).replace("Source evidence", "Build plan").replace("source evidence", "build plan")
            await self.events.emit_tool_status(invocation.id, "failed", summary, [], ToolResult(
                invocation_id=invocation.id, status="failed", summary=summary))
            return
        summary = "Investigation draft saved. Review its fixed inputs, proposed budget and gaps; execution and publication are not authorized."
        await self.events.emit_tool_status(invocation.id, "completed", summary, [], ToolResult(
            invocation_id=invocation.id, status="completed", summary=summary,
            object_refs=[f"build_plan:{record.plan_id}"], requires_followup=True,
            followup_reason="build_plan_review", followup_prompt="Review the investigation plan before authorizing any work.",
            next_recommended_tools=[READ_BUILD_PLAN_TOOL]))


class BuildPlanReadToolHandler:
    def __init__(self, queries: BuildPlanQueryApplicationService, events: ToolStatusEventPort, access: EvidenceToolAccessPort):
        self.queries, self.events, self.access = queries, events, access

    async def handle(self, invocation: ToolInvocation) -> None:
        try:
            self.access.require_invocation_project_scope(invocation)
            request = BuildPlanReadInput.model_validate(query_payload(invocation.input_payload))
            receipt = await asyncio.to_thread(self.queries.execute, request)
            self.access.require_invocation_project_scope(invocation)
        except Exception as exc:
            if isinstance(exc, (SourceAccessDenied, StaleSourceAccessScope)):
                summary = "Build plan access was denied or changed; reload its fixed inputs."
            elif isinstance(exc, BuildPlanIntegrityError):
                summary = "Build plan failed integrity verification."
            else:
                summary = "Build plan could not be read; check the project and saved plan reference."
            await self.events.emit_tool_status(invocation.id, "failed", summary, [], ToolResult(
                invocation_id=invocation.id, status="failed", summary=summary))
            return
        summary = "Fixed investigation plan verified. Proposed work and budgets are not execution or publication authorization."
        await self.events.emit_tool_status(invocation.id, "completed", summary, [], ToolResult(
            invocation_id=invocation.id, status="completed", summary=summary, build_plan_query=receipt))
