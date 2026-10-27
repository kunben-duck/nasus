from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Callable, Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from ...domain.system_image.image_revision import ImageRevisionIntegrityError, ImageRevisionPageTooLarge
from ...domain.system_image.link_decisions import LinkDecision, LINK_REVIEW_POLICY, assertion_evidence_digest
from ...domain.system_image.source_access import SourceAccessDenied
from ...domain.system_image.source_snapshots import snapshot_digest
from .reference_links import ReferenceLinkApplicationService, StoredReferenceProposal


class LinkReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    proposal_id: StrictStr = Field(min_length=1, max_length=128)
    assertion_id: StrictStr = Field(min_length=1, max_length=128)
    proposal_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    policy_revision: Literal[LINK_REVIEW_POLICY]
    expected_previous_decision_id: Optional[StrictStr] = Field(max_length=128)
    decision: Literal["accept", "reject", "defer"]
    reason: StrictStr = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def nonempty_reason(cls, value):
        if not value.strip():
            raise ValueError("review reason cannot be blank")
        return value


@dataclass(frozen=True)
class LinkDecisionPage:
    project_id: str
    proposal_id: str
    assertion_id: str
    image_revision_id: str
    proposal_digest: str
    evidence_digest: str
    policy_revision: str
    head_decision_id: Optional[str]
    total: int
    items: tuple[LinkDecision, ...]
    next_offset: Optional[int]
    publication: str = "not_in_image_membership"


class LinkDecisionRepositoryPort(Protocol):
    def selected(self, project_id: str, proposal_id: str, decision_ids: tuple[str, ...]) -> tuple[LinkDecision, ...]: ...
    def record(self, request: LinkReviewInput, proposal: StoredReferenceProposal, *, actor_id: str,
               invocation_id: str, recorded_at: str, require_current: Callable[[], None]) -> LinkDecision: ...
    def history(self, project_id: str, proposal_id: str, assertion_id: str,
                through_decision_id: Optional[str]) -> tuple[LinkDecision, ...]: ...


class LinkDecisionApplicationService:
    def __init__(self, references: ReferenceLinkApplicationService, repository: LinkDecisionRepositoryPort):
        self.references, self.repository = references, repository

    def _assertion(self, project_id, proposal_id, assertion_id):
        # Re-authorize the entire frozen input before exposing even review metadata.
        self.references.read(project_id, proposal_id, limit=1)
        saved = self.references.repository.get(project_id, proposal_id)
        if assertion_id not in saved.assertion_ids:
            raise KeyError("reference assertion not found")
        assertion = saved.proposal.assertions[saved.assertion_ids.index(assertion_id)]
        return saved, assertion

    def review(self, request: LinkReviewInput, *, invocation_id: str, recorded_at: str) -> LinkDecision:
        scope = self.references.authorization.scope(request.project_id)
        if scope.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("link review requires a project reviewer")
        saved, assertion = self._assertion(request.project_id, request.proposal_id, request.assertion_id)
        if request.proposal_digest != saved.digest or request.evidence_digest != assertion_evidence_digest(assertion):
            raise ImageRevisionIntegrityError("review does not match the pinned evidence")
        current = lambda: self.references.authorization.require_current(scope)
        current()
        result = self.repository.record(request, saved, actor_id=scope.actor_id, invocation_id=invocation_id,
                                        recorded_at=recorded_at, require_current=current)
        if (any(getattr(result, key) != getattr(request, key) for key in (
                "project_id", "proposal_id", "assertion_id", "proposal_digest", "evidence_digest", "policy_revision", "decision", "reason"))
                or result.previous_decision_id != request.expected_previous_decision_id
                or result.reviewer_actor != scope.actor_id or result.invocation_id != invocation_id
                or result.image_revision_id != saved.proposal.image_revision_id
                or result.assertion_digest != snapshot_digest(asdict(assertion))):
            raise ImageRevisionIntegrityError("stored decision differs from the reviewed assertion")
        current()
        return result

    def read(self, project_id: str, proposal_id: str, assertion_id: str, *, offset=0, limit=20,
             through_decision_id: Optional[str] = None) -> LinkDecisionPage:
        if type(offset) is not int or not 0 <= offset <= 1000 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("invalid review page")
        scope = self.references.authorization.scope(project_id)
        saved, assertion = self._assertion(project_id, proposal_id, assertion_id)
        history = self.repository.history(project_id, proposal_id, assertion_id, through_decision_id)
        if offset > len(history):
            raise ValueError("review offset out of bounds")
        for decision in history:
            if (decision.proposal_digest != saved.digest or decision.assertion_digest != snapshot_digest(asdict(assertion))
                    or decision.evidence_digest != assertion_evidence_digest(assertion)
                    or decision.image_revision_id != saved.proposal.image_revision_id):
                raise ImageRevisionIntegrityError("review evidence pins do not match the proposal")
        end = min(offset + limit, len(history))
        while True:
            result = LinkDecisionPage(project_id, proposal_id, assertion_id, saved.proposal.image_revision_id,
                saved.digest, assertion_evidence_digest(assertion), LINK_REVIEW_POLICY,
                history[-1].decision_id if history else None, len(history), history[offset:end], end if end < len(history) else None)
            if len(json.dumps(asdict(result), ensure_ascii=False).encode("utf-8")) <= 65536:
                break
            if end <= offset + 1:
                raise ImageRevisionPageTooLarge("single review exceeds the response budget")
            end -= 1
        self.references.authorization.require_current(scope)
        return result
