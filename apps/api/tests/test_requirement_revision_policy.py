from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.api.app.application.quality_loop.requirement_revision_models import RequirementRevisionInput
from apps.api.app.application.quality_loop.project_versions import ProjectVersionApplicationService, ProjectVersionApplicationError
from apps.api.app.application.quality_loop.version_delivery import VersionDeliveryApplicationService
from apps.api.app.domain.quality_loop.version_delivery import VersionDeliveryConflict
from apps.api.tests.test_project_version_application import InMemoryProjectVersionWorkspace, StubSystemImageOperations, EmptyContextQueries, invocation


def request(**changes):
    return dict(project_id="project", version_id="version", image_revision_id="image", image_artifact_hash="sha256:" + "a" * 64,
        title="Article editing", text="Only the author may edit", **changes)


@pytest.mark.parametrize("change", [
    {"us_id": "us"}, {"expected_revision_id": "revision"}, {"title": " "}, {"text": "\n"},
    {"clarification_answers": [{"question": "Permission?", "answer": " "}]},
    {"clarification_answers": [{"question": "Permission?", "answer": "Author"}, {"question": " Permission? ", "answer": "Anyone"}]},
    {"confirmed_by_user": True}, {"generation_authorized": True},
])
def test_revision_input_rejects_incomplete_or_implicit_authority(change):
    with pytest.raises(ValidationError):
        RequirementRevisionInput.model_validate({**request(), **change})


def test_bound_projects_never_choose_a_latest_iteration_for_missing_or_foreign_id():
    workspace = InMemoryProjectVersionWorkspace()
    service = ProjectVersionApplicationService(workspace, StubSystemImageOperations(), EmptyContextQueries())
    project = service.create_project_record("Delivery project")
    first = service.create_version_record(project.id, "First")
    second = service.create_version_record(project.id, "Second")
    service.version_delivery = SimpleNamespace(requires_explicit_version=lambda _: True, require_legacy_write=lambda *args: None)
    for version_id in (None, "missing", "foreign-version"):
        with pytest.raises(ProjectVersionApplicationError, match="explicit version_id"):
            service._version(project.id, invocation("version.inputs.import", input_payload={
                "project_id": project.id, **({"version_id": version_id} if version_id else {})}))
    with pytest.raises(ProjectVersionApplicationError, match="explicit delivery iteration"):
        service.active_or_create_quality_version(project.id)
    selected = service._version(project.id, invocation("version.inputs.import", input_payload={"version_id": first.id}))
    assert selected.id == first.id and selected.id != second.id
    assert all(not items for items in workspace.version_us_items.values())


def test_legacy_project_keeps_existing_default_version_behavior():
    workspace = InMemoryProjectVersionWorkspace()
    service = ProjectVersionApplicationService(workspace, StubSystemImageOperations(), EmptyContextQueries())
    project = service.create_project_record("Legacy project")
    selected = service.create_version_record(project.id, "Legacy")
    service.version_delivery = SimpleNamespace(requires_explicit_version=lambda _: False, require_legacy_write=lambda *args: None)
    assert service.active_or_create_quality_version(project.id).id == selected.id


def test_legacy_us_guard_preserves_explicit_old_versions_but_not_bound_iterations():
    repository = SimpleNamespace(enabled=lambda _: True, requirement_version=lambda p, u: "old" if u == "old-us" else "bound",
        read=lambda p, v: (None, None if v == "old" else {"baseline": {}}))
    service = VersionDeliveryApplicationService(repository, None, None, None)
    assert service.require_legacy_us_write("project", "old-us", "old") is None
    for us, version in (("old-us", None), ("old-us", "other"), ("new-us", "bound")):
        with pytest.raises(VersionDeliveryConflict):
            service.require_legacy_us_write("project", us, version)
    repository.enabled = lambda _: False
    assert service.require_legacy_us_write("legacy-project", "old-us", None) is None
