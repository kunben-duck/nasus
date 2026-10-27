from dataclasses import asdict
from typing import Literal, Optional, Protocol, Union

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError, field_validator

from ...domain.system_image.publication import PUBLICATION_POLICY, ROLLBACK_POLICY, PublicationChanged, PublicationIntegrityError
from ...domain.system_image.source_snapshots import snapshot_digest
from .publication_read_models import PublishedImagePin


class PublicationTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    image_revision_id: StrictStr = Field(min_length=1, max_length=128)
    image_artifact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    target_baseline_id: StrictStr = Field(min_length=1, max_length=128)
    expected_head_id: Optional[StrictStr] = Field(..., min_length=1, max_length=128)
    policy_revision: Literal[PUBLICATION_POLICY] = PUBLICATION_POLICY


class PublicationReviewInput(PublicationTarget):
    expected_preview_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_review_id: Optional[StrictStr] = Field(..., min_length=1, max_length=128)
    decision: Literal["approve", "reject"]
    reason: StrictStr = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value):
        if not value.strip():
            raise ValueError("A review reason is required")
        return value


class PublicationPublishInput(PublicationTarget):
    expected_preview_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    approval_id: StrictStr = Field(min_length=1, max_length=128)


class RollbackTarget(PublicationTarget):
    expected_head_id: StrictStr = Field(min_length=1, max_length=128)
    rollback_publication_id: StrictStr = Field(min_length=1, max_length=128)
    policy_revision: Literal[ROLLBACK_POLICY] = ROLLBACK_POLICY


class RollbackReviewInput(RollbackTarget):
    expected_preview_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_review_id: Optional[StrictStr] = Field(..., min_length=1, max_length=128)
    decision: Literal["approve", "reject"]
    reason: StrictStr = Field(min_length=1, max_length=2000)
    meaningful_reason = field_validator("reason")(PublicationReviewInput.meaningful_reason.__func__)


class RollbackPublishInput(RollbackTarget):
    expected_preview_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    approval_id: StrictStr = Field(min_length=1, max_length=128)


class PublicationPreviewReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: Union[PublicationTarget, RollbackTarget]
    preview_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    review_id: Optional[StrictStr]
    review_decision: Optional[Literal["approve", "reject"]]
    quality_generation_authorized: Literal[False] = False
    release_authorized: Literal[False] = False


class PublicationHeadInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    target_baseline_id: StrictStr = Field(min_length=1, max_length=128)


class PublicationHeadPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    publication_id: StrictStr
    image_revision_id: StrictStr
    image_artifact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    sequence: int = Field(ge=1)


class PublicationHeadReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: PublicationHeadInput
    head: Optional[PublicationHeadPin]
    quality_generation_authorized: Literal[False] = False
    release_authorized: Literal[False] = False


def target_of(request):
    model = RollbackTarget if isinstance(request, RollbackTarget) else PublicationTarget
    return model.model_validate({key: getattr(request, key) for key in model.model_fields})


class ImagePublicationRepositoryPort(Protocol):
    def publication(self, project_id, publication_id): ...
    def require_current_pin(self, project_id: str, pin: PublishedImagePin): ...
    def target(self, project_id, baseline_id): ...
    def review_head(self, project_id, claim_digest): ...
    def history(self, project_id, baseline_id, *, after_sequence, limit): ...
    def committed(self, request, *, invocation_id, actor_id, review, require_access): ...
    def review(self, request, preview, *, invocation_id, actor_id, recorded_at, require_current, require_access): ...
    def publish(self, request, preview, *, invocation_id, actor_id, recorded_at, require_current, require_access): ...
    def has_heads(self, project_id): ...


class ImagePublicationApplicationService:
    def __init__(self, images, manifests, authorization, repository: ImagePublicationRepositoryPort):
        self.images, self.manifests = images, manifests
        self.authorization, self.repository = authorization, repository

    def pin(self, project_id, publication_id, *, require_current=False):
        with self.images.verified_read_session(reuse=True):
            return self._pin(project_id, publication_id, require_current=require_current)

    def _pin(self, project_id, publication_id, *, require_current):
        scope = self.authorization.scope(project_id)
        value = self.repository.publication(project_id, publication_id)
        header, _ = self.images.frozen_snapshot(project_id, value["image_revision_id"])
        if (not header.code_member_count or header.artifact_hash != value["image_artifact_hash"]
                or header.manifest_id != value["manifest_id"] or header.manifest_hash != value["manifest_hash"]):
            raise PublicationIntegrityError("Publication does not match the immutable image")
        try:
            pin = PublishedImagePin.model_validate({key: value[key] for key in PublishedImagePin.model_fields})
        except (ValidationError, KeyError) as exc:
            raise PublicationIntegrityError("Stored publication pin is invalid") from exc
        if require_current:
            self.repository.require_current_pin(project_id, pin)
        self.authorization.require_current(scope)
        return pin

    def has_heads(self, project_id):
        scope = self.authorization.scope(project_id)
        result = self.repository.has_heads(project_id)
        self.authorization.require_current(scope)
        return result

    def _verified(self, target):
        header, image = self.images.frozen_snapshot(target.project_id, target.image_revision_id)
        if header.artifact_hash != target.image_artifact_hash or not header.code_member_count:
            raise PublicationIntegrityError("Publication requires an exact image with captured code")
        if not isinstance(target, RollbackTarget):
            latest = self.manifests.latest_manifest(target.project_id)
            if latest is None or latest.manifest_id != header.manifest_id or latest.content_hash != header.manifest_hash:
                raise PublicationChanged("Source manifest changed; rebuild and review the candidate")
        # The artifact validates frozen membership; publication also validates the
        # archived original evidence, not just that an opaque handle exists.
        selection = sorted({(m["object_id"], eid) for m in image["members"] for eid in m["evidence_ids"]})
        for start in range(0, len(selection), 512):
            self.images.verify_evidence_selection(target.project_id, target.image_revision_id, tuple(selection[start:start + 512]))
        return header, image

    def _preview(self, target, *, reuse=False):
        with self.images.verified_read_session(reuse=reuse):
            return self._preview_snapshot(target)

    def _preview_snapshot(self, target):
        scope = self.authorization.scope(target.project_id)
        baseline, head = self.repository.target(target.project_id, target.target_baseline_id)
        if (head["publication_id"] if head else None) != target.expected_head_id:
            raise PublicationChanged("Target head changed; preview again")
        restored = None
        if isinstance(target, RollbackTarget):
            restored = self.repository.publication(target.project_id, target.rollback_publication_id)
            if (head is None or restored["baseline_id"] != target.target_baseline_id
                    or restored["sequence"] >= head["sequence"]
                    or restored["image_revision_id"] != target.image_revision_id
                    or restored["image_artifact_hash"] != target.image_artifact_hash
                    or restored["image_revision_id"] == head["image_revision_id"]):
                raise PublicationChanged("Rollback requires a different historical publication of this exact baseline")
        header, image = self._verified(target)
        if restored is not None and (header.manifest_id != restored["manifest_id"]
                or header.manifest_hash != restored["manifest_hash"]):
            raise PublicationIntegrityError("Rollback source manifest does not match the original publication")
        value = {"target": target.model_dump(mode="json"), "baseline": baseline, "head": head,
            "source_scope": {"acl_epoch": scope.acl_epoch, "binding_ids": sorted(scope.binding_ids)},
            "image": asdict(header), "source_members": image["source_members"],
            "readiness": {"scope": "knowledge_snapshot_only", "quality_generation_authorized": False,
                "release_authorized": False, "unverified_observation_count": sum(m["kind"] == "legacy_observation" for m in image["members"]),
                "limitations": ["Source projections and inferred relations retain their original authority.",
                    "Publication does not approve business expectations, test coverage or target-build execution."]}}
        if restored is not None:
            value["rollback_source"] = restored
            value["readiness"]["limitations"].append("Rollback restores historical knowledge only, not deployed code, source heads or prior approvals.")
        return {**value, "preview_digest": snapshot_digest(value)}

    def preview(self, target: PublicationTarget):
        with self.images.verified_read_session():
            return self._reviewed_preview(target)

    def _reviewed_preview(self, target):
        scope = self.authorization.scope(target.project_id)
        value = self._preview(target, reuse=True)
        claim = snapshot_digest({"target": target.model_dump(mode="json"), "preview_digest": value["preview_digest"]})
        result = {**value, "review": self.repository.review_head(target.project_id, claim),
            "can_review": scope.effective_project_role in {"project_admin", "platform_admin"}}
        self.authorization.require_current(scope)
        return result

    def receipt(self, target):
        value = self.preview(target)
        return PublicationPreviewReceipt(request=target, preview_digest=value["preview_digest"],
            review_id=value["review"]["review_id"] if value["review"] else None,
            review_decision=value["review"]["decision"] if value["review"] else None)

    def head_receipt(self, request: PublicationHeadInput):
        value = self.history(request.project_id, request.target_baseline_id, limit=1)["head"]
        head = PublicationHeadPin.model_validate({key: value[key] for key in PublicationHeadPin.model_fields}) if value else None
        return PublicationHeadReceipt(request=request, head=head)

    def _write(self, request, *, invocation_id, recorded_at, review):
        scope = self.authorization.scope(request.project_id)
        if scope.effective_project_role not in {"project_admin", "platform_admin"}:
            raise PermissionError("Publication requires a project administrator")
        access = lambda: self.authorization.require_current(scope)
        prior = self.repository.committed(request, invocation_id=invocation_id, actor_id=scope.actor_id,
            review=review, require_access=access)
        if prior is not None:
            # Recovery verifies the original image, but never moves a newer head back.
            self.images.frozen_snapshot(request.project_id, request.image_revision_id)
            access()
            return prior
        target = target_of(request)
        value = self._preview(target)
        if value["preview_digest"] != request.expected_preview_digest:
            raise PublicationChanged("Publication preview changed; review again")
        def require_current():
            if self._preview(target)["preview_digest"] != request.expected_preview_digest:
                raise PublicationChanged("Publication inputs changed before commit")
            access()
        operation = self.repository.review if review else self.repository.publish
        return operation(request, value, invocation_id=invocation_id, actor_id=scope.actor_id,
            recorded_at=recorded_at, require_current=require_current, require_access=access)

    def review(self, request: PublicationReviewInput, *, invocation_id, recorded_at):
        return self._write(request, invocation_id=invocation_id, recorded_at=recorded_at, review=True)

    def publish(self, request: PublicationPublishInput, *, invocation_id, recorded_at):
        return self._write(request, invocation_id=invocation_id, recorded_at=recorded_at, review=False)

    def history(self, project_id, baseline_id, *, after_sequence=0, limit=20):
        with self.images.verified_read_session():
            return self._history(project_id, baseline_id, after_sequence=after_sequence, limit=limit)

    def _history(self, project_id, baseline_id, *, after_sequence, limit):
        scope = self.authorization.scope(project_id)
        if type(after_sequence) is not int or after_sequence < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Invalid publication page")
        baseline, head = self.repository.target(project_id, baseline_id)
        page = self.repository.history(project_id, baseline_id, after_sequence=after_sequence, limit=limit)
        for item in ([head] if head else []) + page["items"]:
            header, _ = self.images.frozen_snapshot(project_id, item["image_revision_id"])
            if header.artifact_hash != item["image_artifact_hash"]:
                raise PublicationIntegrityError("Publication image digest mismatch")
        self.authorization.require_current(scope)
        return {"baseline": baseline, "head": head, **page}
