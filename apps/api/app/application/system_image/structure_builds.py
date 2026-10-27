from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from ...domain.system_image.build_plan import BuildPlanIntegrityError
from ...domain.system_image.image_revision import ImageRevisionSummary, require_frozen_inputs
from ...domain.system_image.structure_work import StructureWorkLease
from .build_plans import BuildPlanApplicationService
from .image_candidate_preparation import ImageCandidatePreparation
from .build_lineage import CodeExtractionReceipt


STRUCTURE_EXECUTOR = "nasus.pinned-structure.v1"


class StructureBuildCancelled(RuntimeError):
    pass


class StructureBuildInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: StrictStr = Field(min_length=1, max_length=128)
    plan_id: StrictStr = Field(min_length=1, max_length=128)
    plan_digest: StrictStr = Field(min_length=1, max_length=128)
    target_baseline_id: StrictStr = Field(min_length=1, max_length=128)


@dataclass(frozen=True)
class StructureBuildBinding:
    project_id: str
    plan_id: str
    plan_digest: str
    target_baseline_id: str
    invocation_id: str
    executor_version: str = STRUCTURE_EXECUTOR


@dataclass(frozen=True)
class StructureBuildTarget:
    project_name: str
    version_id: Optional[str]
    confirmed_at: str
    max_active_seconds: Optional[int] = None


@dataclass(frozen=True)
class StructureBuildCommit:
    binding: StructureBuildBinding
    target: StructureBuildTarget
    require_current: Callable[[], None]
    work_lease: Optional[StructureWorkLease] = None
    code_extractions: tuple[CodeExtractionReceipt, ...] = ()


class StructureBuildRepositoryPort(Protocol):
    def validate(self, binding: StructureBuildBinding) -> StructureBuildTarget: ...
    def completed(self, binding: StructureBuildBinding) -> Optional[ImageRevisionSummary]: ...


class StructureBuildApplicationService:
    """Execute one confirmed structural work item, not an autonomous plan grant."""

    def __init__(self, plans: BuildPlanApplicationService, preparation: ImageCandidatePreparation,
                 repository: StructureBuildRepositoryPort, *, lineage=None):
        self.plans, self.preparation, self.repository = plans, preparation, repository
        self.lineage = lineage

    def read_completed(self, request: StructureBuildInput, *, invocation_id: str) -> ImageRevisionSummary:
        """Read the original committed work, without renewing its execution consent."""
        scope = self.plans.authorization.scope(request.project_id)
        plan = self.plans.read(request.project_id, request.plan_id)
        if plan.plan_digest != request.plan_digest:
            raise BuildPlanIntegrityError("Completed structure plan digest changed.")
        revision = self.repository.completed(StructureBuildBinding(**request.model_dump(), invocation_id=invocation_id))
        if (revision is None or revision.project_id != request.project_id
                or revision.baseline_id != request.target_baseline_id
                or revision.manifest_id != plan.proposal.intent.source_manifest_id
                or revision.manifest_hash != plan.proposal.intent.source_manifest_hash
                or revision.status != "candidate"):
            raise BuildPlanIntegrityError("Completed structure is not this fixed plan's candidate.")
        if self.lineage is not None:
            self.lineage.read(request.project_id, request.plan_id, revision.image_revision_id, revision.artifact_hash)
        self.plans.authorization.require_current(scope)
        return revision

    def execute(self, request: StructureBuildInput, *, invocation_id: str,
                work_lease: Optional[StructureWorkLease] = None,
                require_work: Optional[Callable[[], None]] = None) -> ImageRevisionSummary:
        if (work_lease is None) != (require_work is None):
            raise BuildPlanIntegrityError("Structural worker ownership needs its current fence.")
        if require_work:
            require_work()
        scope = self.plans.authorization.scope(request.project_id)
        plan = self.plans.read(request.project_id, request.plan_id)
        if plan.plan_digest != request.plan_digest:
            raise BuildPlanIntegrityError("The confirmed plan digest does not match the saved plan.")
        work = next((item for item in plan.proposal.work_items if item.work_item_id == "structure"), None)
        if (work is None or work.capability != "immutable_structure_extraction" or work.dependency_ids
                or work.max_model_calls != 0 or work.max_tool_calls != 1 or work.max_attempts != 1
                or set(work.source_binding_ids) != {source.binding_id for source in plan.proposal.intent.sources}):
            raise BuildPlanIntegrityError("Plan has no supported structural work item.")
        manifest = self.plans.manifests.get_manifest(request.project_id, plan.proposal.intent.source_manifest_id)
        if (manifest.project_id != request.project_id or manifest.members != plan.proposal.intent.sources
                or manifest.content_hash != plan.proposal.intent.source_manifest_hash):
            raise BuildPlanIntegrityError("Structural work inputs do not match the plan.")
        require_frozen_inputs(manifest)
        binding = StructureBuildBinding(**request.model_dump(), invocation_id=invocation_id)
        target = self.repository.validate(binding)
        self.plans.authorization.require_current(scope)

        def verify_revision(revision):
            if (revision.project_id != request.project_id or revision.baseline_id != request.target_baseline_id
                    or revision.manifest_id != manifest.manifest_id or revision.manifest_hash != manifest.content_hash
                    or revision.status != "candidate" or revision.publication != "blocked_pending_revision_governance"):
                raise BuildPlanIntegrityError("Structural artifact does not match the confirmed inputs and target.")

        existing = self.repository.completed(binding)
        if existing is not None:
            verify_revision(existing)
            if self.lineage is not None:
                self.lineage.read(request.project_id, request.plan_id, existing.image_revision_id, existing.artifact_hash)
            self.plans.authorization.require_current(scope)
            return existing

        def require_current():
            if require_work:
                require_work()
            self.plans.authorization.require_current(scope)
            confirmed = datetime.fromisoformat(target.confirmed_at)
            elapsed = (datetime.now(timezone.utc) - confirmed).total_seconds()
            seconds = min(plan.proposal.intent.budget.max_active_seconds,
                          target.max_active_seconds or plan.proposal.intent.budget.max_active_seconds)
            if not 0 <= elapsed <= seconds:
                raise TimeoutError("Confirmed structural work exceeded its time budget.")

        def check_phase():
            require_current()
            if self.repository.validate(binding) != target:
                raise BuildPlanIntegrityError("Structural build target changed during execution.")

        check_phase()
        result = self.preparation.prepare(manifest, project_name=target.project_name,
            baseline_id=request.target_baseline_id, version_id=target.version_id,
            invocation_id=invocation_id, recorded_at=target.confirmed_at,
            check_phase=check_phase, build_commit=StructureBuildCommit(binding, target, require_current, work_lease))
        verify_revision(result.revision)
        self.plans.authorization.require_current(scope)
        return result.revision
