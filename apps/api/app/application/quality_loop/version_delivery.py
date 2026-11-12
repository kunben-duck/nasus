from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from ...domain.quality_loop.version_delivery import (
    VersionDeliveryConflict, VersionDeliveryIntegrityError, require_matching_pin,
)
from ..platform.project_models import VersionCreateRequest
from .version_delivery_models import delivery_view


class VersionDeliveryRepositoryPort(Protocol):
    def enabled(self, project_id): ...
    def read(self, project_id, version_id): ...
    def code_revisions(self, project_id, members): ...
    def requirement_version(self, project_id, us_id): ...
    def create(self, project_id, request, *, invocation_id, actor_id, expected_role, recorded_at,
               prepare, verify, require_access): ...


class VersionDeliveryApplicationService:
    def __init__(self, repository: VersionDeliveryRepositoryPort, publications, images, authorization):
        self.repository = repository
        self.publications = publications
        self.images = images
        self.authorization = authorization

    def require_legacy_creation(self, project_id):
        if self.repository.enabled(project_id):
            raise VersionDeliveryConflict("image_binding is required for this delivery-enabled project")

    def requires_explicit_version(self, project_id):
        return self.repository.enabled(project_id)

    def require_legacy_write(self, project_id, version_id):
        _, binding = self.repository.read(project_id, version_id)
        if binding is not None:
            raise VersionDeliveryConflict("This image-bound iteration requires the formal delivery command path")

    def require_legacy_us_write(self, project_id, us_id, version_id):
        if not self.repository.enabled(project_id):
            return
        actual_version = self.repository.requirement_version(project_id, us_id)
        if not version_id or version_id != actual_version:
            raise VersionDeliveryConflict("Select the requirement's exact iteration before a quality command")
        self.require_legacy_write(project_id, actual_version)

    def _prepare(self, project_id, request):
        if request.image_binding is None:
            return None
        requested = request.image_binding
        with self.images.verified_read_session(reuse=True):
            pin = self.publications.pin(project_id, requested.publication_id, require_current=True)
            require_matching_pin(requested, pin)
            header, members = self.images.frozen_source_members(project_id, pin.image_revision_id)
            if header.artifact_hash != pin.image_artifact_hash:
                raise VersionDeliveryIntegrityError("Published image changed during binding")
            code = self.repository.code_revisions(project_id, members)
        if not code:
            raise VersionDeliveryConflict("Published image must contain captured code")
        return {"baseline": pin.model_dump(mode="json"), "iteration_image": pin.model_dump(mode="json"),
                "code_revisions": code}

    def _verify(self, project_id, binding):
        if binding is None:
            return
        with self.images.verified_read_session(reuse=True):
            for key in ("baseline", "iteration_image"):
                stored = binding[key]
                pin = self.publications.pin(project_id, stored["publication_id"], require_current=False)
                if pin.model_dump(mode="json") != stored:
                    raise VersionDeliveryIntegrityError("Stored Version image pin cannot be verified")
            _, members = self.images.frozen_source_members(project_id, binding["iteration_image"]["image_revision_id"])
            # Repository/ref labels are the original captured values, not live
            # binding projections. Only immutable revision facts fence history.
            revision_keys = ("binding_id", "source_revision_id", "external_revision", "commit_sha", "content_hash", "manifest_hash")
            frozen = lambda values: [{key: value[key] for key in revision_keys} for value in values]
            if frozen(self.repository.code_revisions(project_id, members)) != frozen(binding["code_revisions"]):
                raise VersionDeliveryIntegrityError("Stored Version source revisions cannot be verified")

    def create(self, project_id, invocation):
        request = VersionCreateRequest.model_validate({"name": "New Version", **{key: invocation.input_payload[key]
            for key in VersionCreateRequest.model_fields if key in invocation.input_payload}})
        request = request.model_copy(update={"name": request.name.strip()})
        if not request.name:
            raise ValueError("name is required")
        scope = self.authorization.scope(project_id)
        version, binding = self.repository.create(project_id, request, invocation_id=invocation.id,
            actor_id=scope.actor_id, expected_role=scope.effective_project_role,
            recorded_at=datetime.now(timezone.utc).isoformat(),
            prepare=lambda: self._prepare(project_id, request),
            verify=lambda value: self._verify(project_id, value),
            require_access=lambda: self.authorization.require_current(scope))
        self.authorization.require_current(scope)
        return version, delivery_view(project_id, version, binding)

    def read(self, project_id, version_id):
        scope = self.authorization.scope(project_id)
        version, binding = self.repository.read(project_id, version_id)
        self._verify(project_id, binding)
        result = delivery_view(project_id, version, binding)
        self.authorization.require_current(scope)
        return result
