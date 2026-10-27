"""Activate a reviewed source revision through the existing governed command surface."""
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from .agent_models import AgentGoal, AgentStep
from ...domain.agent.image_plan_phases import ImagePlanPhase
from ...domain.agent.resume_checkpoint import AgentResumeCheckpoint
from ...domain.system_image.build_authorization import ApprovedBuildBudget
from ...domain.system_image.build_plan import BuildPlanIntegrityError
from ..system_image.build_authorizations import ApprovedBuildBudgetInput


ACTIVATE_PLAN_REVISION_TOOL = "system_image.build.plan.activate_revision"


class ImagePlanPhaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: StrictStr = Field(min_length=1, max_length=128)
    goal_id: StrictStr = Field(min_length=1, max_length=128)
    root_plan_id: StrictStr = Field(min_length=1, max_length=128)
    revision_id: StrictStr = Field(min_length=1, max_length=128)
    revision_hash: StrictStr = Field(min_length=1, max_length=128)
    parent_phase_id: Optional[StrictStr] = None
    parent_phase_hash: Optional[StrictStr] = None
    budget: ApprovedBuildBudgetInput
    expected_goal: Dict[str, Any]

    def checkpoint(self):
        value = AgentResumeCheckpoint.capture(self.expected_goal)
        if (value.project_id, value.goal_id) != (self.project_id, self.goal_id):
            raise BuildPlanIntegrityError("Phase activation belongs to another goal.")
        return value


@dataclass(frozen=True)
class StoredImagePlanPhase:
    phase: ImagePlanPhase
    phase_hash: str


class ImagePlanPhaseRepositoryPort(Protocol):
    def activate(self, request, revision, *, actor_id, invocation_id, created_at, require_current): ...
    def history(self, project_id, root_plan_id, goal_id): ...
    def verify_goal(self, goal: AgentGoal): ...


def phase_steps(goal, phase_id, request, revision, target_baseline_id):
    fixed = {"project_id": goal.project_id, "plan_id": revision.plan_id, "plan_digest": revision.plan_digest,
             "target_baseline_id": target_baseline_id}
    tools = [("query.system_image.build_plans.read", {"project_id": goal.project_id, "plan_id": revision.plan_id}),
             ("system_image.build.authorize", {**fixed, "budget": request.budget.model_dump()}),
             ("system_image.build.structure", fixed)]
    result = []
    for number, (tool, payload) in enumerate(tools, 1):
        result.extend([AgentStep(id=f"phase_{phase_id}_act_{number}", title=f"Execute {tool}", phase="acting", status="pending",
            selected_tool_id=tool, tool_input_payload={**payload, "goal_template": goal.goal_template,
                "goal_description": goal.summary, "tool_plan_index": len(goal.steps) + number}),
            AgentStep(id=f"phase_{phase_id}_observe_{number}", title=f"Observe {tool}", status="pending")])
    result.append(AgentStep(id=f"phase_{phase_id}_decide", title="Review enriched image artifacts", status="pending"))
    return result


class ImagePlanPhaseApplicationService:
    def __init__(self, plans, repository: ImagePlanPhaseRepositoryPort):
        self.plans, self.repository = plans, repository

    def require_access(self, request):
        scope = self.plans.authorization.scope(request.project_id)
        request.checkpoint()
        records = self.plans.revisions.history(request.project_id, request.root_plan_id, request.goal_id)
        matches = [record for record in records if (record.revision.revision_id, record.revision_hash)
                   == (request.revision_id, request.revision_hash)]
        if len(matches) != 1:
            raise BuildPlanIntegrityError("Activation requires its exact source-enrichment revision.")
        revision = matches[0].revision
        plan = self.plans.read(request.project_id, revision.plan_id)
        ApprovedBuildBudget(**request.budget.model_dump()).validate_plan(plan.proposal)
        self.plans.authorization.require_current(scope)
        return scope, revision

    def activate(self, request, *, invocation_id, created_at):
        scope, revision = self.require_access(request)
        return self.repository.activate(request, revision, actor_id=scope.actor_id, invocation_id=invocation_id,
            created_at=created_at, require_current=lambda: self.plans.authorization.require_current(scope))

    def verify_goal(self, goal):
        records, start = self.repository.verify_goal(goal)
        if records:
            self._verify_records(goal.project_id, records[0].phase.root_plan_id, goal.id, records)
        return start

    def _verify_records(self, project_id, root_plan_id, goal_id, records):
        scope = self.plans.authorization.scope(project_id)
        revisions = self.plans.revisions.history(project_id, root_plan_id, goal_id)
        for record in records:
            phase = record.phase
            matches = [item for item in revisions if item.revision.revision_id == phase.revision_id]
            if len(matches) != 1 or (matches[0].revision_hash, matches[0].revision.plan_id,
                    matches[0].revision.plan_digest, matches[0].revision.source_manifest_id,
                    matches[0].revision.source_manifest_hash) != (phase.revision_hash, phase.plan_id,
                    phase.plan_digest, phase.source_manifest_id, phase.source_manifest_hash):
                raise BuildPlanIntegrityError("Plan phase differs from its immutable source-enrichment revision.")
            plan = self.plans.read(project_id, phase.plan_id)
            if (plan.plan_digest, plan.proposal.intent.source_manifest_id, plan.proposal.intent.source_manifest_hash) != (
                    phase.plan_digest, phase.source_manifest_id, phase.source_manifest_hash):
                raise BuildPlanIntegrityError("Activated plan changed its source pins.")
        self.plans.authorization.require_current(scope)

    def history(self, project_id, root_plan_id, goal_id):
        scope = self.plans.authorization.scope(project_id)
        self.plans.read(project_id, root_plan_id)
        records = self.repository.history(project_id, root_plan_id, goal_id)
        self._verify_records(project_id, root_plan_id, goal_id, records)
        self.plans.authorization.require_current(scope)
        return records
