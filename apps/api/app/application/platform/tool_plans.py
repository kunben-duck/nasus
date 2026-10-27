from __future__ import annotations

from ..system_image.build_plan_queries import BuildPlanQueryApplicationService, BuildPlanReadInput, READ_BUILD_PLAN_TOOL
from .errors import PlatformApplicationError
from .tool_evidence import ToolEvidenceInvocationPort
from .tool_handlers.evidence import EvidenceToolAccessPort
from .tool_handlers.query_input import query_payload


class ToolBuildPlanObservationApplicationService:
    def __init__(self, invocations: ToolEvidenceInvocationPort, plans: BuildPlanQueryApplicationService,
                 access: EvidenceToolAccessPort):
        self.invocations, self.plans, self.access = invocations, plans, access

    def describe(self, invocation_id: str, project_id: str) -> dict | None:
        invocation = self.invocations.get_tool_invocation(invocation_id)
        if invocation.tool_id != READ_BUILD_PLAN_TOOL:
            return None
        self.access.require_invocation_project_scope(invocation)
        if invocation.status != "completed":
            return None
        expected = BuildPlanReadInput.model_validate(query_payload(invocation.input_payload))
        if expected.project_id != project_id:
            raise PlatformApplicationError("build_plan_project_mismatch", "Build plan belongs to another project.", 403)
        receipt = invocation.result.build_plan_query if invocation.result else None
        if receipt is None or invocation.result.status != "completed" or receipt.request != expected:
            raise PlatformApplicationError("build_plan_receipt_mismatch", "Build plan receipt does not match its invocation.", 409)
        plan = self.plans.expand(receipt)
        self.access.require_invocation_project_scope(invocation)
        return self.plans.describe(plan, receipt)
