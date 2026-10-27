from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from ...domain.agent.resume_checkpoint import AgentResumeCheckpoint
from ...domain.system_image.build_plan import BuildPlanIntegrityError
from ...domain.system_image.build_plan_revisions import BuildPlanRevision, enriched_proposal
from .build_plans import BuildPlanApplicationService


REVISE_PLAN_TOOL = "system_image.build.plan.revise"


class BuildPlanRevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: StrictStr = Field(min_length=1, max_length=128)
    goal_id: StrictStr = Field(min_length=1, max_length=128)
    root_plan_id: StrictStr = Field(min_length=1, max_length=128)
    from_plan_id: StrictStr = Field(min_length=1, max_length=128)
    from_plan_digest: StrictStr = Field(min_length=1, max_length=128)
    source_manifest_id: StrictStr = Field(min_length=1, max_length=128)
    parent_revision_id: Optional[StrictStr] = None
    parent_revision_hash: Optional[StrictStr] = None
    expected_goal: Dict[str, Any]

    def checkpoint(self):
        checkpoint = AgentResumeCheckpoint.capture(self.expected_goal)
        if (checkpoint.goal_id, checkpoint.project_id) != (self.goal_id, self.project_id):
            raise BuildPlanIntegrityError("Revision checkpoint belongs to another goal.")
        return checkpoint


@dataclass(frozen=True)
class StoredBuildPlanRevision:
    revision: BuildPlanRevision
    revision_hash: str


@dataclass(frozen=True)
class BuildPlanRevisionGoal:
    goal_id: str
    title: str
    pause_reason: str


class BuildPlanRevisionRepositoryPort(Protocol):
    def record(self, request: BuildPlanRevisionInput, proposal, *, actor_id: str, invocation_id: str,
               created_at: str, require_current: Callable[[], None]) -> StoredBuildPlanRevision: ...
    def history(self, project_id: str, root_plan_id: str, goal_id: str) -> list[StoredBuildPlanRevision]: ...
    def eligible_goals(self, project_id: str, root_plan_id: str) -> list[BuildPlanRevisionGoal]: ...


class BuildPlanRevisionApplicationService:
    def __init__(self, plans: BuildPlanApplicationService, repository: BuildPlanRevisionRepositoryPort):
        self.plans, self.repository = plans, repository

    def require_access(self, request: BuildPlanRevisionInput):
        scope = self.plans.authorization.scope(request.project_id)
        request.checkpoint()
        self.plans.read(request.project_id, request.root_plan_id)
        previous = self.plans.read(request.project_id, request.from_plan_id)
        if previous.plan_digest != request.from_plan_digest:
            raise BuildPlanIntegrityError("Original plan digest changed.")
        manifest = self.plans.manifests.get_manifest(request.project_id, request.source_manifest_id)
        if manifest.project_id != request.project_id or manifest.manifest_id != request.source_manifest_id:
            raise BuildPlanIntegrityError("Enrichment manifest scope mismatch.")
        for item in manifest.members:
            scope.require_binding(item.binding_id)
        proposal = enriched_proposal(previous.proposal, manifest)
        self.plans.authorization.require_current(scope)
        return scope, proposal

    def revise(self, request, *, invocation_id, created_at):
        scope, proposal = self.require_access(request)
        record = self.repository.record(request, proposal, actor_id=scope.actor_id,
            invocation_id=invocation_id, created_at=created_at,
            require_current=lambda: self.plans.authorization.require_current(scope))
        self._verify(record)
        revision = record.revision
        if (revision.project_id, revision.goal_id, revision.root_plan_id, revision.from_plan_id,
                revision.from_plan_digest, revision.source_manifest_id, revision.plan_digest, revision.checkpoint,
                revision.invocation_id) != (request.project_id, request.goal_id, request.root_plan_id,
                request.from_plan_id, request.from_plan_digest, request.source_manifest_id,
                proposal.digest, request.checkpoint(), invocation_id):
            raise BuildPlanIntegrityError("Saved revision differs from its canonical request.")
        self.plans.authorization.require_current(scope)
        return record

    @staticmethod
    def _verify(record):
        record.revision.require_valid()
        if record.revision_hash != record.revision.digest:
            raise BuildPlanIntegrityError("Build plan revision digest changed.")

    def history(self, project_id, root_plan_id, goal_id):
        scope = self.plans.authorization.scope(project_id)
        self.plans.read(project_id, root_plan_id)
        records = self.repository.history(project_id, root_plan_id, goal_id)
        if len(records) > 80:
            raise BuildPlanIntegrityError("Revision history exceeds its bounded ledger.")
        previous = None
        for number, record in enumerate(records, 1):
            self._verify(record)
            item = record.revision
            if (item.project_id, item.root_plan_id, item.goal_id, item.revision_number,
                    item.parent_revision_id, item.parent_revision_hash, item.from_plan_id) != (
                    project_id, root_plan_id, goal_id, number,
                    previous.revision.revision_id if previous else None,
                    previous.revision_hash if previous else None,
                    previous.revision.plan_id if previous else root_plan_id):
                raise BuildPlanIntegrityError("Revision history is not its complete same-goal chain.")
            old = self.plans.read(project_id, item.from_plan_id)
            new = self.plans.read(project_id, item.plan_id)
            manifest = self.plans.manifests.get_manifest(project_id, item.source_manifest_id)
            if (old.plan_digest != item.from_plan_digest or new.plan_digest != item.plan_digest
                    or manifest.content_hash != item.source_manifest_hash
                    or enriched_proposal(old.proposal, manifest) != new.proposal):
                raise BuildPlanIntegrityError("Revision proposal no longer matches its source pins.")
            previous = record
        self.plans.authorization.require_current(scope)
        return records

    def eligible_goals(self, project_id, root_plan_id):
        scope = self.plans.authorization.scope(project_id)
        self.plans.read(project_id, root_plan_id)
        result = self.repository.eligible_goals(project_id, root_plan_id)
        self.plans.authorization.require_current(scope)
        return result
