from dataclasses import asdict, dataclass
from typing import Callable, Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from ...domain.system_image.build_plan import BuildPlanIntegrityError
from ...domain.system_image.investigation import (
    InvestigationEvidence, InvestigationReview, REFERENCE_INVESTIGATION_POLICY, propose_investigation,
)
from ...domain.system_image.source_access import SourceAccessDenied
from .build_plans import BuildPlanApplicationService
from .image_query_models import ImageEvidenceInput
from .image_query_tools import ImageQueryToolPort
from .image_revision_queries import ImageRevisionQueryApplicationService


INVESTIGATE_TOOL = "system_image.build.investigate"
INVESTIGATION_READ_TOOL = "query.system_image.build_investigations.read"


class InvestigationEvidenceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    object_id: StrictStr = Field(min_length=1, max_length=256)
    evidence_id: StrictStr = Field(min_length=1, max_length=128)


class InvestigationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    plan_id: StrictStr = Field(min_length=1, max_length=128)
    plan_digest: StrictStr = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    goal_id: StrictStr = Field(min_length=1, max_length=128)
    image_revision_id: StrictStr = Field(min_length=1, max_length=128)
    image_artifact_hash: StrictStr = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    parent_revision_id: Optional[StrictStr] = Field(default=None, min_length=1, max_length=128)
    parent_revision_hash: Optional[StrictStr] = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    evidence_selection: tuple[InvestigationEvidenceSelection, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def parent_pair(self):
        if (self.parent_revision_id is None) != (self.parent_revision_hash is None):
            raise ValueError("Parent revision and hash must be supplied together.")
        if len({(item.object_id, item.evidence_id) for item in self.evidence_selection}) != len(self.evidence_selection):
            raise ValueError("Evidence selection cannot contain duplicates.")
        return self


class InvestigationReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    revision_id: StrictStr = Field(min_length=1, max_length=128)


class InvestigationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["investigation_revision"] = "investigation_revision"
    project_id: StrictStr = Field(min_length=1, max_length=128)
    revision_id: StrictStr = Field(min_length=1, max_length=128)
    revision_hash: StrictStr = Field(pattern=r"^sha256:[a-f0-9]{64}$")


@dataclass(frozen=True)
class StoredInvestigation:
    revision_id: str
    revision_hash: str
    request: InvestigationInput
    revision_number: int
    created_at: str
    review: InvestigationReview


class InvestigationRepositoryPort(Protocol):
    def require_goal(self, request: InvestigationInput) -> None: ...
    def has_structure_artifact(self, request: InvestigationInput, image_revision_id: str, baseline_id: str) -> bool: ...
    def read(self, project_id: str, revision_id: str) -> StoredInvestigation: ...
    def record(self, request: InvestigationInput, review: InvestigationReview, *, invocation_id: str,
               actor_id: str, created_at: str, require_current: Callable[[], None]) -> StoredInvestigation: ...


class InvestigationApplicationService:
    def __init__(self, plans: BuildPlanApplicationService, images: ImageRevisionQueryApplicationService,
                 image_tools: ImageQueryToolPort, repository: InvestigationRepositoryPort):
        self.plans, self.images, self.image_tools, self.repository = plans, images, image_tools, repository

    def require_access(self, request):
        plan = self.plans.read(request.project_id, request.plan_id)
        if plan.plan_digest != request.plan_digest:
            raise BuildPlanIntegrityError("Investigation plan digest changed.")
        self.repository.require_goal(request)
        return plan

    def create(self, request, *, invocation_id, actor_id, created_at):
        scope = self.plans.authorization.scope(request.project_id)
        if scope.actor_id != actor_id:
            raise BuildPlanIntegrityError("Investigation actor mismatch.")
        if scope.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("Investigation requires current reviewer authority.")
        plan = self.require_access(request)
        previous = self.read(request.project_id, request.parent_revision_id) if request.parent_revision_id else None
        if previous and (previous.revision_hash != request.parent_revision_hash
                or (previous.request.plan_id, previous.request.plan_digest, previous.request.goal_id)
                != (request.plan_id, request.plan_digest, request.goal_id)):
            raise BuildPlanIntegrityError("Investigation parent differs from the fixed goal and plan.")
        if previous and previous.review.state == "paused_budget":
            raise BuildPlanIntegrityError("Paused investigation requires new independently reviewed inputs or budget.")
        with self.images.verified_read_session():
            header, payload = self.images.frozen_snapshot(request.project_id, request.image_revision_id)
            if header.artifact_hash != request.image_artifact_hash:
                raise BuildPlanIntegrityError("Investigation candidate digest changed.")
            # Only the plan's committed structure, or an explicitly chained child,
            # may seed investigation. An arbitrary same-manifest image is insufficient.
            ancestor = header
            for _ in range(16):
                if self.repository.has_structure_artifact(request, ancestor.image_revision_id, header.baseline_id):
                    break
                if not ancestor.parent_revision_id:
                    raise BuildPlanIntegrityError("Candidate is not descended from this plan's structural artifact.")
                parent, _ = self.images.frozen_snapshot(request.project_id, ancestor.parent_revision_id)
                if parent.artifact_hash != ancestor.parent_artifact_hash or parent.baseline_id != header.baseline_id:
                    raise BuildPlanIntegrityError("Investigation candidate lineage is invalid.")
                ancestor = parent
            else:
                raise BuildPlanIntegrityError("Investigation lineage exceeds its bounded depth.")
            members = sorted((item for item in payload["members"] if item["kind"] in {"code_entity", "source_document"}),
                             key=lambda item: (item["kind"] != "source_document", item["object_id"]))
            evidence = []
            selected = request.evidence_selection or tuple(InvestigationEvidenceSelection(
                object_id=item["object_id"], evidence_id=sorted(item["evidence_ids"])[0])
                for item in members if item["evidence_ids"])[:8]
            by_id = {item["object_id"]: item for item in members}
            for selection in selected:
                item = by_id.get(selection.object_id)
                if item is None or selection.evidence_id not in item["evidence_ids"]:
                    raise BuildPlanIntegrityError("Selected investigation evidence is outside this fixed image.")
                body = ImageEvidenceInput(project_id=request.project_id, image_revision_id=request.image_revision_id,
                    object_id=item["object_id"], evidence_id=selection.evidence_id, max_lines=20)
                receipt = self.image_tools.execute(body)
                if receipt.source_revision_id != item["source_revision_id"]:
                    raise BuildPlanIntegrityError("Investigation evidence receipt changed source.")
                evidence.append(InvestigationEvidence(item["object_id"], body.evidence_id,
                    receipt.source_revision_id, receipt.result_hash))
            review = propose_investigation(plan.proposal, header.image_revision_id, payload, tuple(evidence),
                previous=previous.review if previous else None,
                policy_version=previous.review.policy_version if previous else REFERENCE_INVESTIGATION_POLICY)
            if previous and previous.review.state == "paused_no_progress" and review.no_progress_rounds > 0:
                raise BuildPlanIntegrityError("Paused investigation requires verified new evidence, not another retry.")
        self.plans.authorization.require_current(scope)
        stored = self.repository.record(request, review, invocation_id=invocation_id, actor_id=actor_id,
            created_at=created_at, require_current=lambda: self.plans.authorization.require_current(scope))
        self.plans.authorization.require_current(scope)
        return stored

    def read(self, project_id, revision_id):
        # Parent history and evidence share one operation, not a cross-request
        # cache. Every raw read and live permission check still runs.
        with self.images.verified_read_session(reuse=True):
            return self._read_verified(project_id, revision_id)

    def _read_verified(self, project_id, revision_id):
        record = self.repository.read(project_id, revision_id)
        if not 1 <= record.revision_number <= 80:
            raise BuildPlanIntegrityError("Investigation history exceeds its bound.")
        plan = self.require_access(record.request)
        previous = self.read(project_id, record.request.parent_revision_id) if record.request.parent_revision_id else None
        if record.revision_number != (previous.revision_number + 1 if previous else 1):
            raise BuildPlanIntegrityError("Investigation parent sequence is invalid.")
        header, payload = self.images.frozen_snapshot(project_id, record.request.image_revision_id)
        rebuilt = propose_investigation(plan.proposal, header.image_revision_id, payload, record.review.verified_evidence,
            previous=previous.review if previous else None, policy_version=record.review.policy_version)
        if (rebuilt.digest != record.review.digest or header.artifact_hash != record.request.image_artifact_hash
                or (previous and previous.revision_hash != record.request.parent_revision_hash)):
            raise BuildPlanIntegrityError("Investigation revision failed replay verification.")
        for pin in record.review.verified_evidence:
            receipt = self.image_tools.execute(ImageEvidenceInput(project_id=project_id,
                image_revision_id=record.request.image_revision_id, object_id=pin.object_id,
                evidence_id=pin.evidence_id, max_lines=20))
            if receipt.result_hash != pin.result_hash or receipt.source_revision_id != pin.source_revision_id:
                raise BuildPlanIntegrityError("Investigation evidence failed replay verification.")
        return record

    @staticmethod
    def describe(record):
        return {"revision_id": record.revision_id, "revision_hash": record.revision_hash,
            "request": record.request.model_dump(mode="json"), "revision_number": record.revision_number,
            "created_at": record.created_at, "review": asdict(record.review)}
