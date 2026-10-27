from __future__ import annotations

from typing import Callable, Protocol

from pydantic import BaseModel, ConfigDict, conint

from ...domain.system_image.build_authorization import ApprovedBuildBudget, BuildExecutionAuthorization, STRUCTURE_BUILD_TOOL
from ...domain.system_image.build_plan import BuildPlanIntegrityError
from ...domain.system_image.image_revision import require_frozen_inputs
from .build_plans import BuildPlanApplicationService, StoredBuildPlan
from .structure_builds import StructureBuildInput


class ApprovedBuildBudgetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_tool_calls: conint(strict=True, ge=1, le=1000)
    max_model_calls: conint(strict=True, ge=0, le=1000)
    max_active_seconds: conint(strict=True, ge=1, le=86400)
    max_cost_microusd: conint(strict=True, ge=0, le=10**9)


class BuildAuthorizationInput(StructureBuildInput):
    budget: ApprovedBuildBudgetInput


class BuildAuthorizationRepositoryPort(Protocol):
    def authorize(self, request: BuildAuthorizationInput, plan: StoredBuildPlan, *, invocation_id: str,
                  actor_id: str, require_current: Callable[[], None]) -> BuildExecutionAuthorization: ...
    def reserve(self, invocation_id: str, *, require_current: Callable[[], None]) -> bool: ...


class BuildAuthorizationApplicationService:
    def __init__(self, plans: BuildPlanApplicationService, repository: BuildAuthorizationRepositoryPort):
        self.plans, self.repository = plans, repository

    def authorize(self, request: BuildAuthorizationInput, *, invocation_id: str) -> BuildExecutionAuthorization:
        scope = self.plans.authorization.scope(request.project_id)
        plan = self.plans.read(request.project_id, request.plan_id)
        if plan.plan_digest != request.plan_digest:
            raise BuildPlanIntegrityError("Execution consent requires the exact saved plan digest.")
        budget = ApprovedBuildBudget(**request.budget.model_dump())
        budget.validate_plan(plan.proposal)
        work = next((item for item in plan.proposal.work_items if item.work_item_id == "structure"), None)
        if (work is None or work.proposed_tool_id != STRUCTURE_BUILD_TOOL or work.dependency_ids
                or work.max_attempts != 1 or work.max_tool_calls != 1 or work.max_model_calls != 0
                or work.capability != "immutable_structure_extraction"):
            raise BuildPlanIntegrityError("The proposed structure executor is not supported.")
        manifest = self.plans.manifests.get_manifest(request.project_id, plan.proposal.intent.source_manifest_id)
        if manifest.content_hash != plan.proposal.intent.source_manifest_hash or manifest.members != plan.proposal.intent.sources:
            raise BuildPlanIntegrityError("Execution consent inputs differ from the saved plan.")
        require_frozen_inputs(manifest)
        return self.repository.authorize(request, plan, invocation_id=invocation_id, actor_id=scope.actor_id,
            require_current=lambda: self.plans.authorization.require_current(scope))

    def reserve_execution(self, invocation) -> bool:
        if invocation.tool_id != STRUCTURE_BUILD_TOOL or not invocation.input_payload.get("agent_goal_id"):
            return False
        request = StructureBuildInput.model_validate({key: invocation.input_payload.get(key) for key in (
            "project_id", "plan_id", "plan_digest", "target_baseline_id")})
        scope = self.plans.authorization.scope(request.project_id)
        plan = self.plans.read(request.project_id, request.plan_id)
        if plan.plan_digest != request.plan_digest:
            raise BuildPlanIntegrityError("Execution request differs from the approved plan.")
        return self.repository.reserve(invocation.id,
            require_current=lambda: self.plans.authorization.require_current(scope))
