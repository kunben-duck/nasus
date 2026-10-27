from dataclasses import asdict, dataclass
from typing import Callable, Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from ...domain.agent.resume_checkpoint import AgentResumeCheckpoint
from ...domain.system_image.build_plan import BuildPlanIntegrityError
from ...domain.system_image.gap_ownership import (GapResponsibility, OWNERSHIP_SCHEMA,
    ownership_view, report_gaps, validate_responsibilities)
from ...domain.system_image.source_access import SourceAccessDenied
from ...domain.system_image.owned_build_completion import CompletionOwnershipProof


ASSIGN_GAPS_TOOL = "system_image.build.gaps.assign"


class ResponsibilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    gap_id: StrictStr = Field(pattern=r"^gap_[a-f0-9]{64}$")
    owner_actor_id: StrictStr = Field(min_length=1, max_length=128)
    reason: StrictStr = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def valid_responsibility(self):
        GapResponsibility(**self.model_dump())
        return self


class GapOwnershipInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    completion_invocation_id: StrictStr = Field(min_length=1, max_length=128)
    completion_report_hash: StrictStr = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    expected_goal: dict
    parent_revision_id: Optional[StrictStr] = Field(default=None, min_length=1, max_length=128)
    parent_revision_hash: Optional[StrictStr] = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    assignments: tuple[ResponsibilityInput, ...] = Field(min_length=1, max_length=96)

    @model_validator(mode="after")
    def valid_scope(self):
        if (AgentResumeCheckpoint.capture(self.expected_goal).project_id != self.project_id
                or (self.parent_revision_id is None) != (self.parent_revision_hash is None)
                or len({item.gap_id for item in self.assignments}) != len(self.assignments)):
            raise ValueError("Gap ownership requires one fixed project/checkpoint and distinct assignments.")
        return self


class GapOwnershipReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["build_gap_ownership"] = "build_gap_ownership"
    project_id: StrictStr
    completion_invocation_id: StrictStr
    completion_report_hash: StrictStr
    revision_id: StrictStr
    revision_hash: StrictStr


@dataclass(frozen=True)
class StoredGapOwnership:
    revision_id: str
    revision_hash: str
    revision_number: int
    invocation_id: str
    confirmed_by: str
    created_at: str
    request: GapOwnershipInput


class GapOwnershipRepositoryPort(Protocol):
    def history(self, project_id: str, completion_invocation_id: str) -> tuple[StoredGapOwnership, ...]: ...
    def eligible_owners(self, project_id: str, owner_ids: tuple[str, ...]) -> set[str]: ...
    def owner_options(self, project_id: str) -> list[dict]: ...
    def record(self, request: GapOwnershipInput, *, invocation_id: str, actor_id: str, created_at: str,
               require_current: Callable[[], None]) -> StoredGapOwnership: ...


class GapOwnershipApplicationService:
    def __init__(self, completions, observations, repository: GapOwnershipRepositoryPort):
        self.completions, self.observations, self.repository = completions, observations, repository

    def _report(self, project_id, invocation_id):
        report = self.observations.describe(invocation_id, project_id, require_base=True)
        if report is None:
            raise BuildPlanIntegrityError("Gap responsibilities require an existing completed assessment.")
        return report

    def require_access(self, request):
        # The observer reauthorizes the original private inputs before expanding
        # them; a report hash or assignment never becomes a source permission.
        report = self._report(request.project_id, request.completion_invocation_id)
        if (self.completions.receipt_hash(report) != request.completion_report_hash
                or report["goal_checkpoint"] != asdict(AgentResumeCheckpoint.capture(request.expected_goal))):
            raise BuildPlanIntegrityError("Gap ownership differs from its original completion report or checkpoint.")
        validate_responsibilities(report_gaps(report), tuple(GapResponsibility(**item.model_dump()) for item in request.assignments))
        return report

    def create(self, request, *, invocation_id, actor_id, created_at):
        self.require_access(request)
        authorization = self.completions.investigations.plans.authorization
        scope = authorization.scope(request.project_id)
        if scope.actor_id != actor_id or scope.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("Confirmed gap responsibilities require current reviewer authority.")
        return self.repository.record(request, invocation_id=invocation_id, actor_id=actor_id, created_at=created_at,
            require_current=lambda: authorization.require_current(scope))

    def owner_options(self, project_id, completion_invocation_id):
        self._report(project_id, completion_invocation_id)
        authorization = self.completions.investigations.plans.authorization
        scope = authorization.scope(project_id)
        if scope.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("Gap owner selection requires current reviewer authority.")
        options = self.repository.owner_options(project_id)
        authorization.require_current(scope)
        return options

    def read(self, project_id, completion_invocation_id, *, revision_id=None):
        report = self._report(project_id, completion_invocation_id)
        report_hash = self.completions.receipt_hash(report)
        gaps = report_gaps(report)
        scope = self.completions.investigations.plans.authorization.scope(project_id)
        history = self.repository.history(project_id, completion_invocation_id)
        for revision in history:
            if (revision.request.completion_report_hash != report_hash
                    or asdict(AgentResumeCheckpoint.capture(revision.request.expected_goal)) != report["goal_checkpoint"]):
                raise BuildPlanIntegrityError("Gap history has changed its original report.")
            validate_responsibilities(gaps, tuple(GapResponsibility(**item.model_dump()) for item in revision.request.assignments))
        current = history[-1] if history else None
        if revision_id is not None:
            current = next((item for item in history if item.revision_id == revision_id), None)
            if current is None:
                raise BuildPlanIntegrityError("The exact gap responsibility revision is unavailable.")
        assignments = tuple(GapResponsibility(**item.model_dump()) for item in current.request.assignments) if current else ()
        eligible = self.repository.eligible_owners(project_id, tuple({item.owner_actor_id for item in assignments}))
        self.completions.investigations.plans.authorization.require_current(scope)
        return {"schema": OWNERSHIP_SCHEMA, "project_id": project_id, "completion_invocation_id": completion_invocation_id,
            "completion_report_hash": report_hash, "revision_id": current.revision_id if current else None,
            "revision_hash": current.revision_hash if current else None,
            "revision_number": current.revision_number if current else 0,
            "is_current_revision": revision_id is None or bool(history and current == history[-1]),
            "gaps": ownership_view(gaps, assignments, eligible),
            "history": [{"revision_id": item.revision_id, "revision_hash": item.revision_hash,
                "revision_number": item.revision_number, "invocation_id": item.invocation_id,
                "confirmed_by": item.confirmed_by, "created_at": item.created_at,
                "assignments": [value.model_dump() for value in item.request.assignments]} for item in history],
            "goal_completed": False, "publication_authorized": False, "execution_authorized": False}

    def resolve_completion(self, pin, expected_goal, *, require_current):
        project_id = AgentResumeCheckpoint.capture(expected_goal).project_id
        report = self._report(project_id, pin.completion_invocation_id)
        if (report.get("schema") != "nasus.image-build-completion.v2"
                or self.completions.receipt_hash(report) != pin.completion_report_hash
                or report["goal_checkpoint"] != asdict(AgentResumeCheckpoint.capture(expected_goal))):
            raise BuildPlanIntegrityError("Completion responsibilities require the exact original v2 report and checkpoint.")
        scope = self.completions.investigations.plans.authorization.scope(project_id)
        gaps = report_gaps(report)
        history = self.repository.history(project_id, pin.completion_invocation_id)
        selected = None
        for revision in history:
            if (revision.request.completion_report_hash != pin.completion_report_hash
                    or asdict(AgentResumeCheckpoint.capture(revision.request.expected_goal)) != report["goal_checkpoint"]):
                raise BuildPlanIntegrityError("Responsibility history differs from the original assessment.")
            validate_responsibilities(gaps, tuple(GapResponsibility(**item.model_dump()) for item in revision.request.assignments))
            if revision.revision_id == pin.revision_id:
                selected = revision
        if selected is None or selected.revision_hash != pin.revision_hash:
            raise BuildPlanIntegrityError("The selected responsibility revision is missing or changed.")
        assignments = tuple(GapResponsibility(**item.model_dump()) for item in selected.request.assignments)
        if require_current:
            owner_ids = tuple(sorted({item.owner_actor_id for item in assignments}))
            if self.repository.eligible_owners(project_id, owner_ids) != set(owner_ids):
                raise BuildPlanIntegrityError("A new completion assessment requires currently eligible gap owners.")
        # Historical reports pin the confirmed fact, not today's member status or
        # newest revision. Current-use gates must recheck eligibility separately.
        self.completions.investigations.plans.authorization.require_current(scope)
        return report, CompletionOwnershipProof(pin.completion_invocation_id, pin.completion_report_hash,
            selected.revision_id, selected.revision_hash, assignments)

    @staticmethod
    def receipt(stored):
        return GapOwnershipReceipt(project_id=stored.request.project_id,
            completion_invocation_id=stored.request.completion_invocation_id,
            completion_report_hash=stored.request.completion_report_hash,
            revision_id=stored.revision_id, revision_hash=stored.revision_hash)
