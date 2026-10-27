"""Complete parent reuse inside one read; specimens are not native business gold."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.run_plan_inputs import RunPlanCommandScope
from apps.api.app.application.quality_loop.run_plans import RunPlanApplicationService
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.automation_script_review import ScriptReviewIntegrityError
from apps.api.app.domain.quality_loop.run_plan import RunPlanChanged, RunPlanIntegrityError, compile_run_plan
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_automation_script_reviews import review_service
from apps.api.tests.test_run_plans import plan_inputs


def saved_review():
    service, draft, request, auth, repo, artifacts = review_service()
    metadata = service.review(request, invocation_id="independent-review", recorded_at="2026-10-10T00:00:00+00:00")
    return service, draft, request, auth, repo, artifacts, metadata


def test_review_returns_the_exact_verified_script_and_preserves_public_view(monkeypatch):
    service, draft, _, _, _, _, metadata = saved_review()
    expected = service.read("p", metadata["revision_id"])
    reads, original = [], service.scripts.read
    def read(project, revision):
        reads.append((project, revision))
        return original(project, revision)
    monkeypatch.setattr(service.scripts, "read", read)
    view, parent = service.read_with_script("p", metadata["revision_id"])
    assert view == expected and parent == draft
    assert reads == [("p", metadata["script_revision_id"])]
    parent["current_use"]["input_current"] = False
    fresh, _ = service.read_with_script("p", metadata["revision_id"])
    assert fresh == expected and len(reads) == 2
    assert not view["current_use"]["execution_authorized"]


@pytest.mark.parametrize("failure", ["source", "archive", "final", "missing"])
def test_review_parent_is_not_returned_when_any_original_verification_fails(monkeypatch, failure):
    service, _, _, auth, repo, artifacts, metadata = saved_review()
    def denied(*_args):
        raise SourceAccessDenied("explicit read failure")
    if failure == "source":
        monkeypatch.setattr(service.scripts, "read", denied)
    elif failure == "archive":
        artifacts.bodies[metadata["artifact_hash"]]["assessment"]["passed_count"] = 1
    elif failure == "final":
        monkeypatch.setattr(auth, "require_current", denied)
    else:
        def missing(*_args):
            raise KeyError("original revision missing")
        monkeypatch.setattr(repo, "revision", missing)
    with pytest.raises((SourceAccessDenied, ScriptReviewIntegrityError, KeyError)):
        service.read_with_script("p", metadata["revision_id"])


def test_review_parent_read_rechecks_current_input_and_withdrawal_without_rewriting_history():
    service, draft, request, auth, _, _, first = saved_review()
    original, _ = service.read_with_script("p", first["revision_id"])
    draft["current_use"]["input_current"] = False
    changed, parent = service.read_with_script("p", first["revision_id"])
    assert parent["current_use"]["input_current"] is False
    assert changed["assessment"] == original["assessment"] and not changed["current_use"]["review_complete"]
    draft["current_use"]["input_current"] = True
    withdrawal = request.model_copy(update={"expected_previous_revision_id": first["revision_id"],
        "decision": "withdraw", "actions": None, "assertions": None})
    service.review(withdrawal, invocation_id="withdrawal", recorded_at="2026-10-10T01:00:00+00:00")
    historical, _ = service.read_with_script("p", first["revision_id"])
    assert historical["assessment"] == original["assessment"] and not historical["current_use"]["review_current"]
    auth.revoked = True
    with pytest.raises(SourceAccessDenied):
        service.read_with_script("p", first["revision_id"])


def parent_reader():
    draft, review, sources, selection = plan_inputs()
    calls = []
    def duplicated(*_args):
        raise AssertionError("a verified parent must not be read a second time")
    def parents(project, revision):
        assert (project, revision) == (selection.project_id, selection.review_revision_id)
        calls.append("review-and-script")
        return deepcopy(review), deepcopy(draft)
    authorization = SimpleNamespace(scope=lambda *_: SimpleNamespace(),
        require_current=lambda *_: calls.append("current"))
    service = RunPlanApplicationService(SimpleNamespace(read=duplicated),
        SimpleNamespace(read=duplicated, read_with_script=parents),
        SimpleNamespace(run_plan_sources=lambda *_: deepcopy(sources)), authorization, None, None)
    scope = RunPlanCommandScope(**{key: getattr(selection, key) for key in RunPlanCommandScope.model_fields})
    return service, draft, review, sources, selection, scope, calls


@pytest.mark.parametrize("current", [False, True])
def test_run_plan_compiler_consumes_one_verified_parent_without_changing_plan(current):
    service, draft, review, sources, selection, _, calls = parent_reader()
    plan, returned_draft, returned_review = service._compile(selection, current=current)
    assert plan == compile_run_plan(draft, review, selection.model_dump(mode="json"), sources)
    assert returned_draft == draft and returned_review == review and calls == ["review-and-script"]
    assert not plan["execution_authorized"] and plan["passed_count"] == 0


def test_run_plan_receipt_consumes_verified_parent_but_reauthorizes_every_operation():
    service, _, _, _, _, scope, calls = parent_reader()
    service.require_command_inputs_access(scope)
    service.require_command_inputs_access(scope)
    assert calls == ["review-and-script", "current", "review-and-script", "current"]


@pytest.mark.parametrize("operation", ["compile", "receipt"])
@pytest.mark.parametrize("failure", ["script_project", "script_revision", "script_hash", "review_project", "review_revision", "review_hash", "review_script"])
def test_verified_parent_cannot_substitute_different_selection_pins(operation, failure):
    service, draft, review, _, selection, scope, _ = parent_reader()
    if failure.startswith("script_"):
        key = {"script_project": "project_id", "script_revision": "script_revision_id", "script_hash": "artifact_hash"}[failure]
        draft["metadata"][key] = acceptance_digest("other") if key == "artifact_hash" else "another"
    else:
        key = {"review_project": "project_id", "review_revision": "revision_id", "review_hash": "artifact_hash", "review_script": "script_revision_id"}[failure]
        review["revision"][key] = acceptance_digest("other") if key == "artifact_hash" else "another"
    with pytest.raises(ValueError if operation == "compile" else RunPlanIntegrityError):
        if operation == "compile":
            service._compile(selection, current=False)
        else:
            service.require_command_inputs_access(scope)


@pytest.mark.parametrize("input_current,review_complete", [(False, True), (True, False)])
def test_current_compile_still_rejects_stale_script_or_incomplete_review(input_current, review_complete):
    service, draft, review, _, selection, _, _ = parent_reader()
    draft["current_use"]["input_current"] = input_current
    review["current_use"]["review_complete"] = review_complete
    with pytest.raises(RunPlanChanged):
        service._compile(selection, current=True)
