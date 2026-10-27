"""Command changes during source verification; ports are explicit protocol specimens."""
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from apps.api.app.domain.quality_loop.run_plan_case_execution import RunPlanCaseExecutionInvalid
from apps.api.tests.test_run_plan_case_inputs import case_inputs, spec
from apps.api.tests.test_run_plan_fixture_handoff import fixture_inputs


def advancing_command(v, monkeypatch, *, elapsed=0, changed=None):
    original = v.service.commands.original_command
    reads = []
    confirmed = datetime.fromisoformat(v.snapshot["input_payload"]["confirmed_at"])

    def read(*args, **kwargs):
        result = original(*args, **kwargs)
        if reads:
            result["now"] = confirmed + timedelta(seconds=elapsed)
            if changed is not None:
                changed(result["command"])
        else:
            result["now"] = confirmed
        reads.append(deepcopy(result))
        return result

    monkeypatch.setattr(v.service.commands, "original_command", read)
    return reads


@pytest.mark.parametrize("fixture", ["case_inputs", "fixture_inputs"])
@pytest.mark.parametrize("mode", ["prepare", "fence"])
@pytest.mark.parametrize("fault", ["expired", "cancelled", "actor", "selection", "renewed_consent", "unconfirmed",
    "malformed_snapshot", "missing_payload"])
def test_live_inputs_reject_command_changes_during_complete_verification(request, monkeypatch, fixture, mode, fault):
    v = request.getfixturevalue(fixture)
    prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"]) if mode == "fence" else None

    def change(command):
        if fault == "cancelled":
            command["status"] = "cancelled"
        elif fault == "actor":
            command["input_payload"]["confirmed_actor_id"] = "another-actor"
        elif fault == "selection":
            command["input_payload"]["run_id"] = "another-run"
        elif fault == "renewed_consent":
            confirmed = datetime.fromisoformat(command["input_payload"]["confirmed_at"])
            command["input_payload"]["confirmed_at"] = (confirmed + timedelta(seconds=1)).isoformat()
        elif fault == "unconfirmed":
            command["input_payload"]["confirmed_by_user"] = False
        elif fault == "malformed_snapshot":
            command["unrecognized"] = True
        elif fault == "missing_payload":
            del command["input_payload"]

    reads = advancing_command(v, monkeypatch, elapsed=901 if fault == "expired" else 1, changed=change)
    before = deepcopy((v.v.saved, v.v.environment, v.locator, v.snapshot))
    with pytest.raises(RunPlanCaseExecutionInvalid):
        if mode == "prepare":
            v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
        else:
            v.service.require_current(prepared)
    assert len(reads) == 2
    assert (v.v.saved, v.v.environment, v.locator, v.snapshot) == before
    assert len(v.runner.commands) == v.state["initial_request_count"]


@pytest.mark.parametrize("fixture", ["case_inputs", "fixture_inputs"])
@pytest.mark.parametrize("elapsed", [0, 899, 900])
def test_unchanged_command_keeps_original_confirmation_window(request, monkeypatch, fixture, elapsed):
    v = request.getfixturevalue(fixture)
    reads = advancing_command(v, monkeypatch, elapsed=elapsed)
    prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    assert len(reads) == 2 and prepared.scope.selection == v.selection.model_dump(mode="json")
    assert len(v.runner.commands) == v.state["initial_request_count"]


@pytest.mark.parametrize("fixture", ["case_inputs", "fixture_inputs"])
@pytest.mark.parametrize("changed", [False, True])
def test_history_ignores_old_consent_age_but_never_adopts_changed_command(request, monkeypatch, fixture, changed):
    v = request.getfixturevalue(fixture)
    prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    v.snapshot["status"] = "completed"
    v.state["target_up"] = False

    def change(command):
        if changed:
            command["input_payload"]["run_id"] = "replacement-historical-run"

    reads = advancing_command(v, monkeypatch, elapsed=86400, changed=change)
    if changed:
        with pytest.raises(RunPlanCaseExecutionInvalid):
            v.service.historical_inputs(prepared.scope)
    else:
        restored = v.service.historical_inputs(prepared.scope)
        assert restored.scope == prepared.scope and restored.plan == prepared.plan
        assert restored.fixture_captures == prepared.fixture_captures
        if fixture == "fixture_inputs":
            assert restored.fixture_inputs == prepared.fixture_inputs
    assert len(reads) == 2
    assert v.state["health_reads"] == 1
    assert len(v.runner.commands) == v.state["initial_request_count"]
