from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from ...domain.system_image.image_revision import ImageObjectMember, ImageRevisionIntegrityError, verify_image_artifact
from ...domain.system_image.image_membership import ImageAssertionMember, build_reviewed_artifact, assertion_member
from ...domain.system_image.link_decisions import StaleLinkDecision, assertion_evidence_digest
from ...domain.system_image.source_access import SourceAccessDenied
from ...domain.system_image.source_snapshots import CapturedSourceManifest, SourceManifestMember, snapshot_digest
from ...domain.system_image.semantic_membership import ImageSemanticMember, semantic_member
from .image_revision_queries import ImageRevisionQueryApplicationService
from .link_decisions import LinkDecisionApplicationService


class ImageReviewFreezeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    parent_revision_id: StrictStr = Field(min_length=1, max_length=128)
    parent_artifact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    proposal_id: StrictStr = Field(min_length=1, max_length=128)
    proposal_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    decision_ids: tuple[StrictStr, ...] = Field(min_length=1, max_length=1000)


@dataclass(frozen=True)
class ImageReviewCommit:
    request: ImageReviewFreezeInput
    invocation_id: str
    selected: tuple[ImageAssertionMember, ...]
    inherited: tuple[ImageAssertionMember, ...]
    require_current: Callable[[], None]
    inherited_semantics: tuple[ImageSemanticMember, ...] = ()


def pin_assertion(saved, assertion_id, decision):
    if assertion_id not in saved.assertion_ids:
        raise ImageRevisionIntegrityError("reviewed assertion missing from proposal")
    assertion = saved.proposal.assertions[saved.assertion_ids.index(assertion_id)]
    if (decision.assertion_id != assertion_id or decision.proposal_id != saved.proposal_id
            or decision.project_id != saved.proposal.project_id or decision.image_revision_id != saved.proposal.image_revision_id
            or decision.proposal_digest != saved.digest or decision.assertion_digest != snapshot_digest(asdict(assertion))
            or decision.evidence_digest != assertion_evidence_digest(assertion)):
        raise ImageRevisionIntegrityError("decision pins do not match the reference assertion")
    return ImageAssertionMember(assertion_id, saved.proposal_id, saved.proposal.image_revision_id,
        saved.digest, snapshot_digest(asdict(assertion)), decision.evidence_digest, decision.decision_id,
        decision.digest, decision.decision, assertion.subject_object_id, assertion.subject_revision_id,
        assertion.object_id, assertion.object_revision_id, assertion.subject_evidence_ids, assertion.object_evidence_ids)


class ImageMembershipApplicationService:
    def __init__(self, images: ImageRevisionQueryApplicationService, decisions: LinkDecisionApplicationService):
        self.images, self.decisions = images, decisions

    def freeze(self, request: ImageReviewFreezeInput, *, invocation_id: str, recorded_at: str):
        scope = self.images.authorization.scope(request.project_id)
        if scope.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("freezing reviewed membership requires a project reviewer")
        current = lambda: self.images.authorization.require_current(scope)
        replay = self.images.repository.reviewed_invocation(request, invocation_id)
        if replay is not None:
            header, payload = self.images.frozen_snapshot(request.project_id, replay)
            pinned = {item["decision_id"] for item in payload.get("assertion_members", [])
                      if item["proposal_id"] == request.proposal_id and item["proposal_digest"] == request.proposal_digest}
            if (header.parent_revision_id != request.parent_revision_id or header.parent_artifact_hash != request.parent_artifact_hash
                    or not set(request.decision_ids).issubset(pinned)):
                raise ImageRevisionIntegrityError("committed freeze differs from the original request")
            current()
            return header
        header, parent = self.images.frozen_snapshot(request.project_id, request.parent_revision_id)
        if header.artifact_hash != request.parent_artifact_hash:
            raise ImageRevisionIntegrityError("parent artifact pin mismatch")
        if len(set(request.decision_ids)) != len(request.decision_ids) or any(not key or len(key) > 128 for key in request.decision_ids):
            raise ValueError("invalid selected decision IDs")
        self.decisions.references.read(request.project_id, request.proposal_id, limit=1)
        saved = self.decisions.references.repository.get(request.project_id, request.proposal_id)
        if saved.digest != request.proposal_digest:
            raise ImageRevisionIntegrityError("proposal digest mismatch")
        inherited = tuple(assertion_member(item) for item in parent.get("assertion_members", []))
        inherited_ids = {item.assertion_id for item in inherited}
        selected = []
        for decision in self.decisions.repository.selected(request.project_id, saved.proposal_id, request.decision_ids):
            history = self.decisions.repository.history(request.project_id, saved.proposal_id, decision.assertion_id, None)
            if not history or decision != history[-1]:
                raise StaleLinkDecision("selected decision is no longer current")
            if saved.proposal.image_revision_id != header.image_revision_id and decision.assertion_id not in inherited_ids:
                raise ImageRevisionIntegrityError("proposal is outside the parent image")
            selected.append(pin_assertion(saved, decision.assertion_id, decision))
        if len(selected) != len(request.decision_ids):
            raise ImageRevisionIntegrityError("selected decision is outside the pinned proposal")
        payload = build_reviewed_artifact(parent, header.image_revision_id, header.artifact_hash, selected)
        current()
        artifact_ref, artifact_hash = self.images.artifacts.put(request.project_id, payload)
        if artifact_hash != snapshot_digest(payload):
            raise ImageRevisionIntegrityError("reviewed artifact digest mismatch")
        manifest = CapturedSourceManifest(header.manifest_id, header.project_id, header.manifest_hash, "",
            tuple(SourceManifestMember(**item) for item in parent["source_members"]))
        # Source captured_at is not an input to an image artifact; reload the
        # canonical manifest in the repository before the transactional commit.
        members = tuple(ImageObjectMember(**{**item, "evidence_ids": tuple(item["evidence_ids"])}) for item in parent["members"])
        result = self.images.repository.record(manifest, header.baseline_id, artifact_ref=artifact_ref,
            artifact_hash=artifact_hash, members=members, relationship_count=header.relationship_count,
            invocation_id=invocation_id, recorded_at=recorded_at,
            review_commit=ImageReviewCommit(request, invocation_id, tuple(selected), inherited, current,
                tuple(map(semantic_member, parent.get("semantic_assertion_members", [])))))
        verify_image_artifact(payload, result)
        current()
        return result
