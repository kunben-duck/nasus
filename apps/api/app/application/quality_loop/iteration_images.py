import re

from ...domain.quality_loop.version_delivery import VersionDeliveryConflict, VersionDeliveryIntegrityError
from .version_delivery_models import AdoptIterationImage


class IterationImageApplicationService:
    """Adopt frozen code explicitly; never mutate the initial publication binding."""

    def __init__(self, repository, delivery, images, authorization):
        self.repository, self.delivery = repository, delivery
        self.images, self.authorization = images, authorization

    def prepare(self, request):
        scope = self.authorization.scope(request.project_id)
        if scope.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise PermissionError("Image adoption requires project QA lead access")
        current = self.delivery.read(request.project_id, request.version_id)
        if not current.enabled or current.iteration_image is None:
            raise VersionDeliveryConflict("Select an image-bound iteration")
        if (current.iteration_image.image_revision_id, current.iteration_image.image_artifact_hash) != (
                request.expected_image_revision_id, request.expected_image_artifact_hash):
            raise VersionDeliveryConflict("Iteration image changed; review the new head before adoption")
        if request.image_revision_id == request.expected_image_revision_id:
            raise VersionDeliveryConflict("The selected image is already current")
        if not request.reason.strip() or any(not re.fullmatch(r"[0-9a-f]{40}", sha) for sha in request.code_commits.values()):
            raise ValueError("A reason and full lowercase Git commit SHA for each code binding are required")
        with self.images.verified_read_session(reuse=True):
            header, members = self.images.frozen_source_members(request.project_id, request.image_revision_id)
            if header.artifact_hash != request.image_artifact_hash:
                raise VersionDeliveryIntegrityError("Selected image hash does not match frozen evidence")
            code = self.delivery.repository.code_revisions(request.project_id, members)
        if {item["binding_id"] for item in code} != {item.binding_id for item in current.code_revisions}:
            raise VersionDeliveryConflict("Code adoption must retain the iteration's repository bindings")
        if {item["binding_id"]: item["commit_sha"] for item in code} != request.code_commits:
            raise VersionDeliveryConflict("Selected commits do not match the frozen code sources")
        self.authorization.require_current(scope)
        return scope, {"parent_image_revision_id": request.expected_image_revision_id,
            "parent_image_artifact_hash": request.expected_image_artifact_hash,
            "image_revision_id": header.image_revision_id, "image_artifact_hash": header.artifact_hash,
            "baseline_id": header.baseline_id, "manifest_id": header.manifest_id,
            "manifest_hash": header.manifest_hash, "code_revisions": code}

    def option(self, project_id, version_id, image_revision_id):
        current = self.delivery.read(project_id, version_id)
        if not current.enabled or current.iteration_image is None:
            raise VersionDeliveryConflict("Select an image-bound iteration")
        header, members = self.images.frozen_source_members(project_id, image_revision_id)
        code = self.delivery.repository.code_revisions(project_id, members)
        request = AdoptIterationImage(project_id=project_id, version_id=version_id,
            expected_image_revision_id=current.iteration_image.image_revision_id,
            expected_image_artifact_hash=current.iteration_image.image_artifact_hash,
            image_revision_id=header.image_revision_id, image_artifact_hash=header.artifact_hash,
            code_commits={item["binding_id"]: item["commit_sha"] for item in code}, reason="Preview only")
        _, payload = self.prepare(request)
        return {"request": request.model_dump(mode="json", exclude={"reason"}),
            "code_revisions": payload["code_revisions"], "adoption_authorized": False}

    def adopt(self, request, *, invocation_id):
        scope = self.authorization.scope(request.project_id)
        self.images.frozen_header(request.project_id, request.image_revision_id)
        def prepare():
            checked, payload = self.prepare(request)
            if checked.fingerprint != scope.fingerprint:
                raise PermissionError("Source access changed during image adoption")
            return payload
        result = self.repository.append(request, invocation_id=invocation_id, scope=scope,
            prepare=prepare, check=lambda: self.authorization.require_current(scope))
        self.authorization.require_current(scope)
        return result
