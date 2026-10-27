from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictStr, conint

from ...domain.system_image.build_plan import (BuildBudgetProposal, BuildPlanIntegrityError, BuildTarget,
    InvestigationPlan, TargetedBuildIntent, propose_build_plan)
from ...domain.system_image.build_authorization import ApprovedBuildBudget
from ...domain.system_image.source_snapshots import CapturedSourceManifest
from .source_access import SourceScopeAuthorizationPort
from .structure_commands import StructureCommandPage, StructureCommandQueryPort, UNFINISHED_STRUCTURE_STATUSES


class BuildBudgetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_tool_calls: conint(strict=True, ge=1, le=1000) = 80
    max_model_calls: conint(strict=True, ge=1, le=1000) = 30
    max_active_seconds: conint(strict=True, ge=1, le=86400) = 1200
    max_cost_microusd: Optional[conint(strict=True, ge=0, le=10**9)] = None


class BuildTargetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: StrictStr = Field(min_length=1, max_length=128)
    target_baseline_id: StrictStr = Field(min_length=1, max_length=128)
    target_version_id: Optional[StrictStr] = Field(..., min_length=1, max_length=128)
    expected_head_id: Optional[StrictStr] = Field(..., min_length=1, max_length=128)
    expected_head_hash: Optional[StrictStr] = Field(..., pattern=r"^sha256:[a-f0-9]{64}$")


class BuildPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: StrictStr = Field(min_length=1, max_length=128)
    source_manifest_id: StrictStr = Field(min_length=1, max_length=128)
    objective: StrictStr = Field(min_length=1, max_length=2000)
    mode: Literal["initialize", "enrich", "refresh", "repair"] = "initialize"
    purpose: Literal["structure", "behavior", "traceability"] = "structure"
    budget: BuildBudgetInput = Field(default_factory=BuildBudgetInput)
    target: Optional[BuildTargetInput] = None


@dataclass(frozen=True)
class StructureArtifactSummary:
    invocation_id: str
    image_revision_id: str
    target_baseline_id: str
    confirmed_at: str


@dataclass(frozen=True)
class BuildAuthorizationSummary:
    authorization_id: str
    goal_id: str
    target_baseline_id: str
    target_version_id: Optional[str]
    confirmed_at: str
    budget: ApprovedBuildBudget
    work_item_ids: tuple[str, ...]
    reserved_work_item_ids: tuple[str, ...]
    unapproved_work_item_ids: tuple[str, ...]
    publication_allowed: bool = False


@dataclass(frozen=True)
class StoredBuildPlan:
    plan_id: str
    project_id: str
    plan_digest: str
    created_at: str
    proposal: InvestigationPlan
    structural_artifacts: tuple[StructureArtifactSummary, ...] = ()
    execution_authorizations: tuple[BuildAuthorizationSummary, ...] = ()


@dataclass(frozen=True)
class BuildPlanSummary:
    plan_id: str
    plan_digest: str
    created_at: str
    source_manifest_id: str
    state: str
    purpose: str
    work_item_count: int


@dataclass(frozen=True)
class BuildPlanList:
    items: tuple[BuildPlanSummary, ...]
    next_after_id: Optional[str]


class BuildManifestPort(Protocol):
    def get_manifest(self, project_id: str, manifest_id: str) -> CapturedSourceManifest: ...
    def latest_manifest(self, project_id: str) -> Optional[CapturedSourceManifest]: ...


class BuildPublicationPort(Protocol):
    def history(self, project_id: str, baseline_id: str, *, limit: int): ...
    def pin(self, project_id: str, publication_id: str, *, require_current: bool = False): ...


class BuildPlanRepositoryPort(Protocol):
    def verify_target_scope(self, target: BuildTarget) -> None: ...

    def record(self, proposal: InvestigationPlan, *, actor_id: str, invocation_id: str, created_at: str,
               require_current_scope: Callable[[], None]) -> StoredBuildPlan: ...

    def get(self, project_id: str, plan_id: str) -> StoredBuildPlan: ...

    def list(self, project_id: str, *, binding_ids: frozenset[str], after_id: str, limit: int) -> list[StoredBuildPlan]: ...


class BuildPlanApplicationService:
    def __init__(self, manifests: BuildManifestPort, repository: BuildPlanRepositoryPort, authorization: SourceScopeAuthorizationPort,
                 commands: Optional[StructureCommandQueryPort] = None, publications: Optional[BuildPublicationPort] = None):
        self.manifests, self.repository, self.authorization = manifests, repository, authorization
        self.commands = commands
        self.publications = publications
        self.revisions = None
        self.phases = None

    def target(self, project_id: str, baseline_id: str) -> BuildTarget:
        scope = self.authorization.scope(project_id)
        if self.publications is None:
            raise BuildPlanIntegrityError("Build target governance is unavailable.")
        value = self.publications.history(project_id, baseline_id, limit=1)
        baseline, head = value["baseline"], value["head"]
        if (baseline["project_id"], baseline["baseline_id"]) != (project_id, baseline_id):
            raise BuildPlanIntegrityError("Build target belongs to a different scope.")
        result = BuildTarget(project_id, baseline_id, baseline["source_version_id"],
            head["publication_id"] if head else None, head["image_artifact_hash"] if head else None)
        self.repository.verify_target_scope(result)
        self.authorization.require_current(scope)
        return result

    def require_target_current(self, target: BuildTarget) -> None:
        if self.target(target.project_id, target.target_baseline_id) != target:
            raise BuildPlanIntegrityError("The displayed build target changed; prepare a new plan.")

    def _require_target_access(self, plan: StoredBuildPlan) -> None:
        intent = plan.proposal.intent
        if not isinstance(intent, TargetedBuildIntent) or intent.target.expected_head_id is None:
            return
        if self.publications is None:
            raise BuildPlanIntegrityError("Build target governance is unavailable.")
        pin = self.publications.pin(plan.project_id, intent.target.expected_head_id)
        if (pin.baseline_id, pin.image_artifact_hash) != (intent.target.target_baseline_id, intent.target.expected_head_hash):
            raise BuildPlanIntegrityError("The original publication differs from this plan's target.")

    def create(self, request: BuildPlanInput, *, invocation_id: str, created_at: str) -> StoredBuildPlan:
        scope = self.authorization.scope(request.project_id)
        manifest = self.manifests.get_manifest(request.project_id, request.source_manifest_id)
        if (manifest.project_id, manifest.manifest_id) != (request.project_id, request.source_manifest_id):
            raise BuildPlanIntegrityError("Build manifest scope mismatch.")
        for source in manifest.members:
            scope.require_binding(source.binding_id)
        target = BuildTarget(**request.target.model_dump()) if request.target is not None else None
        if target is not None:
            if target.project_id != request.project_id:
                raise BuildPlanIntegrityError("Build target project mismatch.")
            self.require_target_current(target)
        proposal = propose_build_plan(manifest, objective=request.objective, mode=request.mode, purpose=request.purpose,
                                      budget=BuildBudgetProposal(**request.budget.model_dump()), target=target)
        self.authorization.require_current(scope)
        def require_current():
            self.authorization.require_current(scope)
            if target is not None:
                self.require_target_current(target)
        record = self.repository.record(proposal, actor_id=scope.actor_id, invocation_id=invocation_id, created_at=created_at,
                                        require_current_scope=require_current)
        self._verify(record, request.project_id)
        if record.proposal != proposal:
            raise BuildPlanIntegrityError("Persisted proposal does not match the requested plan.")
        self.authorization.require_current(scope)
        return record

    @staticmethod
    def _verify(record: StoredBuildPlan, project_id: str) -> None:
        if (record.project_id != project_id or record.proposal.intent.project_id != project_id
                or record.plan_digest != record.proposal.digest):
            raise BuildPlanIntegrityError("Build plan scope or digest mismatch.")

    def read(self, project_id: str, plan_id: str) -> StoredBuildPlan:
        scope = self.authorization.scope(project_id)
        record = self.repository.get(project_id, plan_id)
        self._verify(record, project_id)
        if record.plan_id != plan_id:
            raise BuildPlanIntegrityError("Build plan identity mismatch.")
        for source in record.proposal.intent.sources:
            scope.require_binding(source.binding_id)
        self._require_target_access(record)
        self.authorization.require_current(scope)
        return record

    def list(self, project_id: str, *, after_id: str = "", limit: int = 20) -> BuildPlanList:
        if type(limit) is not int or not 1 <= limit <= 50 or len(after_id) > 64:
            raise ValueError("Invalid build plan page.")
        scope = self.authorization.scope(project_id)
        records = self.repository.list(project_id, binding_ids=scope.binding_ids, after_id=after_id, limit=limit + 1)
        items = []
        if len(records) > limit + 1:
            raise BuildPlanIntegrityError("Build plan page exceeds its limit.")
        ids = [record.plan_id for record in records]
        if ids != sorted(set(ids)) or any(ident <= after_id for ident in ids):
            raise BuildPlanIntegrityError("Build plan cursor does not advance.")
        for record in records:
            self._verify(record, project_id)
            for source in record.proposal.intent.sources:
                scope.require_binding(source.binding_id)
            self._require_target_access(record)
        for record in records[:limit]:
            items.append(BuildPlanSummary(record.plan_id, record.plan_digest, record.created_at,
                record.proposal.intent.source_manifest_id, record.proposal.state, record.proposal.intent.purpose,
                len(record.proposal.work_items)))
        self.authorization.require_current(scope)
        return BuildPlanList(tuple(items), records[limit - 1].plan_id if len(records) > limit else None)

    def unfinished_structure_commands(self, project_id: str, plan_id: str, *, plan_digest: str,
                                      after_id: str = "", limit: int = 20) -> StructureCommandPage:
        if type(limit) is not int or not 1 <= limit <= 50 or len(after_id) > 128:
            raise ValueError("Invalid structural command page.")
        scope = self.authorization.scope(project_id)
        plan = self.read(project_id, plan_id)
        if plan.plan_digest != plan_digest or self.commands is None:
            raise BuildPlanIntegrityError("Structural command discovery requires the exact saved plan.")
        rows = self.commands.unfinished(project_id=project_id, plan_id=plan_id, plan_digest=plan_digest,
            actor_id=scope.actor_id, after_id=after_id, limit=limit + 1)
        ids = [row.invocation_id for row in rows]
        if (len(rows) > limit + 1 or ids != sorted(set(ids)) or any(ident <= after_id for ident in ids)
                or any(not row.target_baseline_id or row.status not in UNFINISHED_STRUCTURE_STATUSES for row in rows)):
            raise BuildPlanIntegrityError("Structural command page is invalid.")
        self.authorization.require_current(scope)
        return StructureCommandPage(project_id, plan_id, plan_digest, tuple(rows[:limit]),
            rows[limit - 1].invocation_id if len(rows) > limit else None)
