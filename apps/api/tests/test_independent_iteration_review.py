from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.independent_iteration_review import IndependentIterationReview
from apps.api.app.domain.system_image.context_pack import ContextPackIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied


def policy(version="nasus.test-design-context.v6"):
    pin = dict(context_id="context", artifact_hash="context-hash", image_revision_id="image", image_artifact_hash="image-hash")
    context = {"metadata": pin, "context": {"policy_version": version}}
    generation = {"generation_id": "generation", "artifact_hash": "generation-hash", "context_pin": deepcopy(pin)}
    result = {"metadata": {"artifact_hash": "generation-hash"}, "result": {"actor_id": "author"}}
    service = IndependentIterationReview(SimpleNamespace(review_identity=lambda *args: deepcopy(context)),
        SimpleNamespace(read=lambda *args: deepcopy(result)))
    return service, context, {"generation_pin": generation}, {"result": {"prepared": {"context_pin": deepcopy(pin)}, "actor_id": "author"}}


@pytest.mark.parametrize("kind", ["cases", "script"])
def test_iteration_requires_other_person_and_preserves_legacy(kind):
    service, context, basis, draft = policy()
    check = getattr(service, kind)
    value = basis if kind == "cases" else draft
    assert not check("project", value, "author")
    assert not check("project", value, "")
    assert check("project", value, "reviewer")
    with pytest.raises(SourceAccessDenied):
        service.require(check("project", value, "author"))
    context["context"]["policy_version"] = "nasus.test-design-context.v4"
    assert check("project", value, "author")


def test_identity_check_cannot_substitute_unverified_context_or_generation():
    service, _, basis, _ = policy()
    basis["generation_pin"]["artifact_hash"] = "other"
    with pytest.raises(ContextPackIntegrityError):
        service.cases("project", basis, "reviewer")
    basis["generation_pin"]["context_pin"]["artifact_hash"] = "other"
    with pytest.raises(ContextPackIntegrityError):
        service.cases("project", basis, "reviewer")


def test_same_person_case_review_is_denied_before_artifact_or_repository_write():
    from apps.api.tests.test_case_approvals import admission_ports, approve
    service, request, state = admission_ports()
    service.independent = SimpleNamespace(cases=lambda *args: False, require=IndependentIterationReview.require)
    assert not service.preview(request.selection())["can_review"]
    with pytest.raises(SourceAccessDenied):
        approve(service, request)
    assert state.rows == [] and state.archives == {}


def test_same_person_script_review_is_denied_before_artifact_or_repository_write():
    from apps.api.tests.test_automation_script_reviews import review_service
    service, _, request, _, repository, artifacts = review_service()
    service.independent = SimpleNamespace(script=lambda *args: False, require=IndependentIterationReview.require)
    assert not service.inspect(request)["can_review"]
    with pytest.raises(SourceAccessDenied):
        service.review(request, invocation_id="self-review", recorded_at="2026-11-16T00:00:00Z")
    assert repository.values == [] and artifacts.bodies == {}
