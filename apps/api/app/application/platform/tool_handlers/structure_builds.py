from __future__ import annotations

import asyncio

from pydantic import ValidationError

from ...system_image.structure_builds import StructureBuildApplicationService, StructureBuildInput, StructureBuildCancelled
from ...system_image.structure_jobs import StructureJobApplicationService
from ....domain.system_image.build_plan import BuildPlanIntegrityError
from ....domain.system_image.code_index import CodeIndexCancelled
from ....domain.system_image.image_revision import ImageRevisionConflict, ImageRevisionIntegrityError
from ....domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from ....domain.system_image.structure_work import StructureWorkCancelled
from ..errors import PlatformApplicationError
from ..tool_invocation_ports import ToolStatusEventPort
from ..tool_models import ToolInvocation, ToolResult
from .evidence import EvidenceToolAccessPort
from .query_input import query_payload


class StructureBuildToolHandler:
    def __init__(self, builds: StructureBuildApplicationService, events: ToolStatusEventPort, access: EvidenceToolAccessPort,
                 jobs: StructureJobApplicationService | None = None):
        self.builds, self.events, self.access = builds, events, access
        self.jobs = jobs

    async def handle(self, invocation: ToolInvocation) -> None:
        try:
            self.access.require_invocation_project_scope(invocation)
            payload = query_payload(invocation.input_payload)
            request = StructureBuildInput.model_validate({key: value for key, value in payload.items()
                if key not in {"confirmed_at", "confirmed_by_user"}})
            if self.jobs is not None and self.jobs.enabled:
                await self.jobs.dispatch(request, invocation.id)
                return
            # Runtime owns the running claim and confirmation, not this handler.
            revision = await asyncio.to_thread(self.builds.execute, request, invocation_id=invocation.id)
            self.access.require_invocation_project_scope(invocation)
        except (StructureWorkCancelled, StructureBuildCancelled, CodeIndexCancelled):
            await self.events.emit_tool_status(invocation.id, "cancelled", "Structural indexing cancelled; no new candidate was committed.", [],
                ToolResult(invocation_id=invocation.id, status="cancelled", summary="Structural indexing cancelled; committed facts are retained."))
            return
        except Exception as exc:
            summary = self.failure_summary(exc)
            await self.events.emit_tool_status(invocation.id, "failed", summary, [], ToolResult(
                invocation_id=invocation.id, status="failed", summary=summary,
                requires_followup=isinstance(exc, TimeoutError),
                followup_reason="build_execution_authorization_review" if isinstance(exc, TimeoutError) else None))
            return
        summary = "Source-pinned structural candidate saved. Semantic investigation and publication still require separate review."
        await self.events.emit_tool_status(invocation.id, "completed", summary,
            [["system-image-revisions", request.project_id], ["system-image-build-plans", request.project_id]],
            ToolResult(invocation_id=invocation.id, status="completed", summary=summary,
                object_refs=[f"build_plan:{request.plan_id}", f"image_revision:{revision.image_revision_id}"],
                requires_followup=True, followup_reason="structural_candidate_review",
                next_recommended_tools=["query.system_image.revisions.read"]))

    @staticmethod
    def failure_summary(exc):
        if isinstance(exc, (SourceAccessDenied, StaleSourceAccessScope, PlatformApplicationError)):
            return "Structural input access was denied or changed; reload the plan before retrying."
        if isinstance(exc, TimeoutError):
            return "Structural work exceeded its confirmed time budget; committed candidates are retained."
        if isinstance(exc, (BuildPlanIntegrityError, ImageRevisionIntegrityError)):
            return "Structural plan, target or artifact integrity verification failed."
        if isinstance(exc, ImageRevisionConflict):
            return "Every selected code source needs a captured revision before structural work can run."
        if isinstance(exc, (ValidationError, ValueError)):
            return "Structural work requires an explicit project, saved plan digest and candidate target baseline."
        return "Structural build could not complete. Check input availability before retrying."
