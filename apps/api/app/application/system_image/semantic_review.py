from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from ...domain.system_image.image_revision import ImageRevisionIntegrityError, ImageRevisionPageTooLarge
from ...domain.system_image.semantic_review import SemanticAssertion, SEMANTIC_REVIEW_POLICY
from ...domain.system_image.source_access import SourceAccessDenied
from ...domain.system_image.source_snapshots import snapshot_digest


@dataclass(frozen=True)
class SemanticDecisionPage:
    assertion: dict
    policy_revision: str
    head_decision_id: Optional[str]
    total: int
    head: Optional[dict]
    items: tuple[dict, ...]
    next_offset: Optional[int]
    publication: str


class SemanticReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    evaluation_id: StrictStr = Field(min_length=1, max_length=128)
    subject_object_id: StrictStr = Field(min_length=1, max_length=128)
    assertion_id: StrictStr = Field(min_length=1, max_length=128)
    assertion_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_previous_decision_id: Optional[StrictStr] = Field(min_length=1, max_length=128)
    policy_revision: Literal[SEMANTIC_REVIEW_POLICY]
    decision: Literal["accept", "reject", "defer"]
    reason: StrictStr = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("a review requires a reason")
        return value


class SemanticReviewRepositoryPort(Protocol):
    def selected(self, project_id, decision_ids): ...
    def history(self, project_id, claim_id, through_decision_id=None): ...
    def record(self, request, assertion, *, actor_id, invocation_id, recorded_at, require_current): ...


class SemanticEvaluationReadPort(Protocol):
    def read(self, project_id, invocation_id): ...


class SemanticReviewApplicationService:
    def __init__(self, evaluations: SemanticEvaluationReadPort, authorization, repository: SemanticReviewRepositoryPort):
        self.evaluations, self.authorization, self.repository = evaluations, authorization, repository

    def assertion(self, project_id, evaluation_id, subject_object_id):
        view = self.evaluations.read(project_id, evaluation_id)
        judgment = next((item for item in view["evaluation"]["judgments"] if item["subject_object_id"] == subject_object_id), None)
        if judgment is None:
            raise KeyError("semantic subject not found")
        selection = view["request"]
        spans = [span for span in view["spans"] if span["object_id"] in {subject_object_id, judgment["target_object_id"]}]
        evidence = lambda object_id: tuple(sorted({span["evidence_id"] for span in spans if span["object_id"] == object_id}))
        return SemanticAssertion(project_id, selection["image_revision_id"], selection["expected_image_hash"], evaluation_id,
            view["artifact_hash"], selection["input_digest"], subject_object_id, judgment["subject_revision_id"],
            judgment["target_object_id"], judgment["target_revision_id"], judgment["relation"], judgment["assessment"],
            evidence(subject_object_id), evidence(judgment["target_object_id"]),
            snapshot_digest({"spans": spans, "evidence": judgment["evidence"], "counterevidence": judgment["counterevidence"],
                             "oracle": judgment["oracle"]}), snapshot_digest(judgment["oracle"]) if judgment["oracle"] else None)

    def review(self, request: SemanticReviewInput, *, invocation_id, recorded_at):
        scope = self.authorization.scope(request.project_id)
        if scope.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("semantic review requires a project reviewer")
        assertion = self.assertion(request.project_id, request.evaluation_id, request.subject_object_id)
        if (request.assertion_id, request.assertion_digest, request.evidence_digest) != (assertion.assertion_id, assertion.digest, assertion.evidence_digest):
            raise ImageRevisionIntegrityError("semantic review pins changed")
        assertion.require_decision(request.decision)
        current = lambda: self.authorization.require_current(scope)
        current()
        result = self.repository.record(request, assertion, actor_id=scope.actor_id, invocation_id=invocation_id,
                                        recorded_at=recorded_at, require_current=current)
        if (result.assertion_id != assertion.assertion_id or result.claim_id != assertion.claim_id
                or result.project_id != request.project_id or result.evaluation_id != assertion.evaluation_id
                or result.image_revision_id != assertion.image_revision_id or result.policy_revision != request.policy_revision
                or result.reviewer_actor != scope.actor_id or result.decision != request.decision or result.reason != request.reason
                or result.assertion_digest != assertion.digest or result.evidence_digest != assertion.evidence_digest
                or result.previous_decision_id != request.expected_previous_decision_id or result.invocation_id != invocation_id):
            raise ImageRevisionIntegrityError("stored semantic decision does not match the request")
        current()
        return result

    def read(self, project_id, evaluation_id, subject_object_id, *, offset=0, limit=20, through_decision_id=None):
        if type(offset) is not int or not 0 <= offset <= 1000 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("invalid semantic review page")
        scope = self.authorization.scope(project_id)
        assertion = self.assertion(project_id, evaluation_id, subject_object_id)
        history = self.repository.history(project_id, assertion.claim_id, through_decision_id)
        if offset > len(history):
            raise ValueError("review offset out of bounds")
        end = min(offset + limit, len(history))
        while True:
            result = {"assertion": {**asdict(assertion), "assertion_id": assertion.assertion_id, "assertion_digest": assertion.digest,
                        "claim_id": assertion.claim_id, "can_accept": assertion.can_accept}, "policy_revision": SEMANTIC_REVIEW_POLICY,
                      "head_decision_id": history[-1].decision_id if history else None, "total": len(history),
                      "head": asdict(history[-1]) if history else None,
                      "items": [asdict(item) for item in history[offset:end]], "next_offset": end if end < len(history) else None,
                      "publication": "not_in_image_membership"}
            if len(json.dumps(result, ensure_ascii=False).encode()) <= 65536:
                break
            if end <= offset + 1:
                raise ImageRevisionPageTooLarge("semantic decision page exceeds response budget")
            end -= 1
        self.authorization.require_current(scope)
        return result
