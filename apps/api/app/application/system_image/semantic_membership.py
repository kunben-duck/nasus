from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from ...domain.system_image.image_membership import ImageAssertionMember, assertion_member
from ...domain.system_image.image_revision import ImageObjectMember, ImageRevisionIntegrityError, verify_image_artifact
from ...domain.system_image.link_decisions import StaleLinkDecision
from ...domain.system_image.semantic_membership import ImageSemanticMember, build_semantic_artifact, semantic_member, FREEZE_SEMANTIC_TOOL
from ...domain.system_image.source_access import SourceAccessDenied
from ...domain.system_image.source_snapshots import CapturedSourceManifest, SourceManifestMember, snapshot_digest
from .image_revision_queries import ImageRevisionQueryApplicationService
from .semantic_review import SemanticReviewApplicationService


class SemanticFreezeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    parent_revision_id: StrictStr = Field(min_length=1, max_length=128)
    parent_artifact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    decision_ids: tuple[StrictStr, ...] = Field(min_length=1, max_length=100)

    @field_validator("decision_ids")
    @classmethod
    def unique_ids(cls, values):
        if len(set(values)) != len(values) or any(not key or len(key) > 128 for key in values):
            raise ValueError("invalid selected semantic decision IDs")
        return values


@dataclass(frozen=True)
class SemanticFreezeCommit:
    request: SemanticFreezeInput
    invocation_id: str
    selected: tuple[ImageSemanticMember, ...]
    inherited: tuple[ImageSemanticMember, ...]
    references: tuple[ImageAssertionMember, ...]
    require_current: Callable[[], None]


class SemanticMembershipApplicationService:
    def __init__(self, images: ImageRevisionQueryApplicationService, reviews: SemanticReviewApplicationService):
        self.images, self.reviews = images, reviews

    def freeze(self, request: SemanticFreezeInput, *, invocation_id: str, recorded_at: str):
        scope = self.images.authorization.scope(request.project_id)
        if scope.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("freezing semantic membership requires a project reviewer")
        current = lambda: self.images.authorization.require_current(scope)
        replay = self.images.repository.reviewed_invocation(request, invocation_id, tool_id=FREEZE_SEMANTIC_TOOL)
        if replay is not None:
            header, payload = self.images.frozen_snapshot(request.project_id, replay)
            pinned = {item["decision"]["decision_id"] for item in payload.get("semantic_assertion_members", [])}
            if (header.parent_revision_id != request.parent_revision_id or header.parent_artifact_hash != request.parent_artifact_hash
                    or not set(request.decision_ids).issubset(pinned)):
                raise ImageRevisionIntegrityError("committed semantic freeze differs from request")
            current()
            return header
        header, parent = self.images.frozen_snapshot(request.project_id, request.parent_revision_id)
        if header.artifact_hash != request.parent_artifact_hash:
            raise ImageRevisionIntegrityError("semantic parent artifact pin mismatch")
        selected = self.reviews.repository.selected(request.project_id, request.decision_ids)
        if len(selected) != len(request.decision_ids):
            raise ImageRevisionIntegrityError("selected semantic decision missing")
        for member in selected:
            assertion, decision = member.assertion, member.decision
            # Re-read the private model artifact and archived evidence through
            # the application port, rather than trusting persisted row hashes.
            if self.reviews.assertion(request.project_id, assertion.evaluation_id, assertion.subject_object_id) != assertion:
                raise ImageRevisionIntegrityError("semantic assertion differs from archived evidence")
            history = self.reviews.repository.history(request.project_id, assertion.claim_id)
            if not history or history[-1] != decision:
                raise StaleLinkDecision("semantic decision changed before freeze")
        payload = build_semantic_artifact(parent, header.image_revision_id, header.artifact_hash, selected)
        current()
        ref, digest = self.images.artifacts.put(request.project_id, payload)
        if digest != snapshot_digest(payload):
            raise ImageRevisionIntegrityError("semantic artifact digest mismatch")
        manifest = CapturedSourceManifest(header.manifest_id, header.project_id, header.manifest_hash, "",
            tuple(SourceManifestMember(**item) for item in parent["source_members"]))
        objects = tuple(ImageObjectMember(**{**item, "evidence_ids": tuple(item["evidence_ids"])}) for item in parent["members"])
        commit = SemanticFreezeCommit(request, invocation_id, tuple(selected),
            tuple(map(semantic_member, parent.get("semantic_assertion_members", []))),
            tuple(map(assertion_member, parent.get("assertion_members", []))), current)
        result = self.images.repository.record(manifest, header.baseline_id, artifact_ref=ref, artifact_hash=digest,
            members=objects, relationship_count=header.relationship_count, invocation_id=invocation_id,
            recorded_at=recorded_at, review_commit=commit)
        verify_image_artifact(payload, result)
        current()
        return result
