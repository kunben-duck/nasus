from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.api.app.application.platform.project_models import VersionCreateRequest, VersionSummary
from apps.api.app.application.platform.tool_models import ToolInvocation
from apps.api.app.application.quality_loop.version_delivery import VersionDeliveryApplicationService
from apps.api.app.application.quality_loop.version_delivery_models import VersionImageBindingInput
from apps.api.app.application.system_image.publication_read_models import PublishedImagePin
from apps.api.app.domain.quality_loop.version_delivery import VersionDeliveryConflict, VersionDeliveryIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied


HASH = "sha256:" + "a" * 64


@pytest.fixture
def service():
    pin = PublishedImagePin(publication_id="pub", baseline_id="base", image_revision_id="img",
        image_artifact_hash=HASH, manifest_id="manifest", manifest_hash=HASH, sequence=1)
    code = [dict(binding_id="binding", source_id="source", source_revision_id="rev", repository="repo",
        tracked_ref="refs/heads/main", external_revision="a" * 40, commit_sha="a" * 40,
        content_hash=HASH, manifest_hash=HASH)]
    version = VersionSummary(id="ver", name="M1", status="draft", branch_name="release/m1",
        us_total=0, us_closed=0, pending_runs=0, pending_approvals=0)
    state = SimpleNamespace(pin=pin, code=code, version=version, binding=None, enabled=False, denied=False, current_calls=[])

    def require_access(scope):
        if state.denied:
            raise SourceAccessDenied("revoked")

    def publication(project_id, publication_id, *, require_current=False):
        state.current_calls.append(require_current)
        require_access(None)
        assert project_id == "project" and publication_id == "pub"
        return pin

    def create(project_id, request, **kwargs):
        if state.enabled and request.image_binding is None:
            raise VersionDeliveryConflict("pin required")
        binding = kwargs["prepare"]()
        kwargs["require_access"]()
        state.binding = binding
        state.enabled = binding is not None
        return version, deepcopy(binding)

    repository = SimpleNamespace(enabled=lambda project: state.enabled,
        read=lambda *args: (version, deepcopy(state.binding)), code_revisions=lambda *args: deepcopy(state.code), create=create)
    images = SimpleNamespace(verified_read_session=lambda **kwargs: nullcontext(),
        frozen_source_members=lambda *args: (SimpleNamespace(artifact_hash=HASH), []))
    authorization = SimpleNamespace(scope=lambda project: SimpleNamespace(actor_id="actor", effective_project_role="qa_lead"),
        require_current=require_access)
    application = VersionDeliveryApplicationService(repository, SimpleNamespace(pin=publication), images, authorization)
    return application, state


def command(**changes):
    return ToolInvocation(id="inv", tool_id="version.create", status="running", summary="creating",
        input_payload={"project_id": "project", "name": "M1", "image_binding": {
            "publication_id": "pub", "image_revision_id": "img", "image_artifact_hash": HASH, "expected_head_id": "pub", **changes}})


def test_pin_contract_and_legacy_read(service):
    application, state = service
    assert VersionCreateRequest(name="old").image_binding is None
    view = application.read("project", "ver")
    assert view.stage == "legacy" and not view.enabled and view.baseline is None
    assert view.code_revisions == view.blockers == view.pending_confirmations == view.available_actions == []
    with pytest.raises(ValidationError):
        VersionImageBindingInput.model_validate({**command().input_payload["image_binding"], "expected_head_id": None})
    with pytest.raises(ValidationError):
        VersionImageBindingInput.model_validate({**command().input_payload["image_binding"], "extra": True})


def test_bound_read_is_historical_and_does_not_claim_m2(service):
    application, state = service
    _, view = application.create("project", command())
    assert view.stage == "image_pinned" and view.baseline == view.iteration_image == state.pin
    assert view.blockers == ["requirement_input_required"] and view.pending_confirmations == []
    assert view.available_actions == ["view_pinned_image"]
    assert state.current_calls == [True]
    assert application.read("project", "ver") == view
    assert state.current_calls == [True, False, False]
    view.code_revisions.clear()
    assert len(application.read("project", "ver").code_revisions) == 1
    with pytest.raises(VersionDeliveryConflict):
        application.require_legacy_creation("project")


@pytest.mark.parametrize("change", [{"expected_head_id": "new"}, {"image_revision_id": "other"},
    {"image_artifact_hash": "sha256:" + "b" * 64}])
def test_mismatching_explicit_pins_never_commit(service, change):
    application, state = service
    with pytest.raises(VersionDeliveryConflict):
        application.create("project", command(**change))
    assert state.binding is None


def test_revoke_and_binding_tamper_fail_closed(service):
    application, state = service
    application.create("project", command())
    state.denied = True
    with pytest.raises(SourceAccessDenied):
        application.read("project", "ver")
    state.denied = False
    state.binding["code_revisions"][0]["commit_sha"] = "b" * 40
    with pytest.raises(VersionDeliveryIntegrityError):
        application.read("project", "ver")


def test_historical_reference_labels_do_not_follow_mutable_binding_projection(service):
    application, state = service
    _, original = application.create("project", command())
    state.code[0]["tracked_ref"] = "refs/heads/next"
    state.code[0]["repository"] = "next-repository"
    assert application.read("project", "ver") == original
