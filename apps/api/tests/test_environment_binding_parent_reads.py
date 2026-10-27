"""Complete parent read-port specimens; not real deployment or performance evidence."""
from copy import deepcopy

import pytest

from apps.api.app.application.quality_loop.run_plan_build_inputs import RunPlanBuildRequest
from apps.api.app.domain.quality_loop.run_plan import RunPlanChanged, RunPlanIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_run_plan_builds import application
from apps.api.tests.test_run_plan_environments import state, spec


def bound():
    service, plan, selection, auth, actions, stored = application()
    request = RunPlanBuildRequest.model_validate(service.preview(selection)["request"])
    metadata = service.bind(request, invocation_id="parent-binding-command", recorded_at="2026-10-13T00:00:00+00:00")
    actions.clear()
    return service, plan, auth, actions, stored, metadata


def test_binding_returns_same_fully_verified_plan_without_second_read_or_authority():
    service, plan, _, actions, _, metadata = bound()
    original = service.read("p", metadata["binding_id"])
    actions.clear()
    view, parent = service.read_with_plan("p", metadata["binding_id"])
    assert view == original and parent == plan and parent is not plan
    assert actions.count("source_read") == actions.count("native_read") == actions.count("private_read") == 1
    assert actions.index("source_read") < actions.index("private_read")
    assert view["current_use"]["execution_authorized"] is False
    assert "put" not in actions and "record" not in actions


def test_binding_pair_rechecks_current_use_and_source_acl_on_every_read():
    service, plan, auth, actions, _, metadata = bound()
    before = service.read_with_plan("p", metadata["binding_id"])[0]
    plan["current_use"]["inputs_current"] = False
    view, parent = service.read_with_plan("p", metadata["binding_id"])
    assert view["artifact"] == before["artifact"]
    assert view["current_use"]["inputs_current"] is parent["current_use"]["inputs_current"] is False
    auth.revoked = True
    actions.clear()
    with pytest.raises(SourceAccessDenied):
        service.read_with_plan("p", metadata["binding_id"])
    assert "private_read" not in actions


@pytest.mark.parametrize("fault", ["archive", "parent", "native", "final_acl"])
def test_binding_pair_never_returns_corrupt_or_unauthorized_parents(monkeypatch, fault):
    service, _, auth, _, stored, metadata = bound()
    if fault == "archive":
        stored["payload"]["binding"]["execution_authorized"] = True
    elif fault in {"parent", "native"}:
        target = service.plans if fault == "parent" else service.builds
        def corrupt(*args):
            raise RunPlanIntegrityError("private original input fault")
        monkeypatch.setattr(target, "read", corrupt)
    else:
        original = service.artifacts.read
        def revoked(*args):
            value = original(*args)
            auth.revoked = True
            return value
        monkeypatch.setattr(service.artifacts, "read", revoked)
    with pytest.raises(SourceAccessDenied if fault == "final_acl" else RunPlanIntegrityError):
        service.read_with_plan("p", metadata["binding_id"])


def paired(state, monkeypatch):
    plan_read = state.service.plans.read
    binding_read = state.service.bindings.read
    def read(project, ident):
        state.actions.append("paired")
        binding = binding_read(project, ident)
        plan = plan_read(project, binding["metadata"]["run_plan_id"])
        return binding, plan
    monkeypatch.setattr(state.service.bindings, "read_with_plan", read, raising=False)


def test_environment_consumes_verified_pair_once_with_identical_complete_response(state, monkeypatch):
    original = state.service._inputs(state.query, current=True)
    state.actions.clear()
    paired(state, monkeypatch)
    actual = state.service._inputs(state.query, current=True)
    assert actual == original and state.actions.count("paired") == 1
    assert state.actions.count("plan") == state.actions.count("binding") == 1
    assert actual[0] is not state.plan and actual[1] is not state.binding
    actual[0]["current_use"]["inputs_current"] = False
    assert state.plan["current_use"]["inputs_current"] is True
    assert "native" not in state.actions


@pytest.mark.parametrize("error", [RunPlanIntegrityError("private archive"), SourceAccessDenied("private source"),
    RuntimeError("private transient storage error")])
def test_pair_failure_propagates_without_fallback_or_target_access(state, monkeypatch, error):
    def fail(*args):
        raise error
    monkeypatch.setattr(state.service.bindings, "read_with_plan", fail, raising=False)
    with pytest.raises(type(error)) as raised:
        state.service._inputs(state.query, current=False)
    assert raised.value is error and state.actions == []


@pytest.mark.parametrize("part,key", [
    ("plan", "project_id"), ("plan", "run_plan_id"), ("plan", "artifact_hash"),
    ("plan", "plan_digest"), ("plan", "image_revision_id"), ("plan", "manifest_id"),
    ("binding", "project_id"), ("binding", "binding_id"), ("binding", "artifact_hash"),
    ("binding", "run_plan_id"), ("binding", "run_plan_artifact_hash"),
    ("binding", "target_artifact_hash"),
])
def test_environment_pair_retains_all_original_plan_binding_and_target_pin_checks(state, monkeypatch, part, key):
    plan, binding = deepcopy((state.plan, state.binding))
    (plan if part == "plan" else binding)["metadata"][key] = "changed-original-pin"
    monkeypatch.setattr(state.service.bindings, "read_with_plan", lambda *_: (binding, plan), raising=False)
    with pytest.raises(RunPlanIntegrityError):
        state.service._inputs(state.query, current=False)
    assert "native" not in state.actions


@pytest.mark.parametrize("part", ["plan", "binding"])
def test_environment_pair_preserves_stale_historical_inputs_without_current_authority(state, monkeypatch, part):
    paired(state, monkeypatch)
    (state.plan if part == "plan" else state.binding)["current_use"]["inputs_current"] = False
    with pytest.raises(RunPlanChanged):
        state.service._inputs(state.query, current=True)
    historical = state.service._inputs(state.query, current=False)
    assert historical[0 if part == "plan" else 1]["current_use"]["inputs_current"] is False
    assert "native" not in state.actions
