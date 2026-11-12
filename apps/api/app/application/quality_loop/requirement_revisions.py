from typing import Protocol

from ...domain.quality_loop.version_delivery import VersionDeliveryConflict
from .requirement_revision_models import RequirementRevisionPage


class RequirementRevisionRepositoryPort(Protocol):
    def append(self, request, *, invocation_id, scope, require_current): ...
    def list(self, project_id, version_id, *, us_id, offset, limit): ...


class RequirementRevisionApplicationService:
    """Version-scoped requirement intake. Drafts do not grant test/release authority."""

    def __init__(self, repository: RequirementRevisionRepositoryPort, delivery, authorization):
        self.repository, self.delivery, self.authorization = repository, delivery, authorization

    def _scope(self, project_id, version_id):
        scope = self.authorization.scope(project_id)
        view = self.delivery.read(project_id, version_id)
        if not view.enabled or view.iteration_image is None:
            raise VersionDeliveryConflict("Requirement revisions require an image-bound delivery iteration")
        self.authorization.require_current(scope)
        return scope, view

    def revise(self, request, *, invocation_id):
        scope, view = self._scope(request.project_id, request.version_id)
        if scope.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise PermissionError("Requirement intake requires a project QA lead")
        if (request.image_revision_id, request.image_artifact_hash) != (
                view.iteration_image.image_revision_id, view.iteration_image.image_artifact_hash):
            raise VersionDeliveryConflict("Requirement image differs from the selected iteration")
        current = lambda: self.authorization.require_current(scope)
        result = self.repository.append(request, invocation_id=invocation_id, scope=scope, require_current=current)
        current()
        return result

    def list(self, project_id, version_id, *, us_id=None, offset=0, limit=20):
        scope, _ = self._scope(project_id, version_id)
        if not 0 <= offset <= 100000 or not 1 <= limit <= 50:
            raise ValueError("Invalid requirement page")
        items = self.repository.list(project_id, version_id, us_id=us_id, offset=offset, limit=limit + 1)
        result = RequirementRevisionPage(project_id=project_id, version_id=version_id,
            items=items[:limit], next_offset=offset + limit if len(items) > limit else None)
        self.authorization.require_current(scope)
        return result
