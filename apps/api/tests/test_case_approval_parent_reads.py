"""Verified parent reuse specimens, not executed coverage or independent gold."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.automation_script_inputs import ScriptExecutionRequest, ScriptExecutionSelection
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.case_approval import CaseApprovalIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_case_approvals import admission_ports, approve
from apps.api.tests.test_automation_scripts import script_executor


def test_parent_read_returns_complete_verified_inputs_without_changing_public_response():
    service, request, state = admission_ports()
    row = approve(service, request)
    public = service.read(request.project_id, row["revision_id"])
    state.calls.clear()
    value, historical, current = service.read_with_inputs(request.project_id, row["revision_id"])
    assert value == public and historical == current == state.prepared
    assert state.calls == ["historical", "current"]
    assert len(historical["cases"]) == len(state.prepared["cases"])
    assert historical["constraint_denominator"] == 2 and historical["obligation_denominator"] == 7
    historical["cases"].clear()
    current["required_constraints"].clear()
    assert service.read_with_inputs(request.project_id, row["revision_id"]) == (public, state.prepared, state.prepared)


@pytest.mark.parametrize("changed", ["mapping", "withdrawal", "input_pin"])
def test_parent_read_keeps_history_but_never_returns_a_stale_live_input(changed):
    service, request, state = admission_ports()
    row = approve(service, request)
    public = service.read(request.project_id, row["revision_id"])
    if changed == "mapping":
        state.current = False
    elif changed == "withdrawal":
        service.review(request.model_copy(update={"decision": "withdraw", "expected_previous_revision_id": row["revision_id"]}),
            invocation_id="withdraw-original", recorded_at="2026-10-13T00:01:00+00:00")
    else:
        def changed_input(_selection):
            value = deepcopy(state.prepared)
            value["mapping_pin"]["request_hash"] = acceptance_digest("different-current-request")
            value["input_digest"] = acceptance_digest({key: item for key, item in value.items() if key != "input_digest"})
            return value
        service.inputs.prepare = changed_input
    value, historical, current = service.read_with_inputs(request.project_id, row["revision_id"])
    assert value["revision"] == public["revision"] and value["basis"] == public["basis"]
    assert historical == state.prepared and current is None
    assert not value["current_use"]["case_admission_current"]


def test_parent_read_detects_a_withdrawal_during_live_input_verification():
    service, request, state = admission_ports()
    row = approve(service, request)
    prepare = service.inputs.prepare

    def withdraw(selection):
        value = prepare(selection)
        service.review(request.model_copy(update={"decision": "withdraw", "expected_previous_revision_id": row["revision_id"]}),
            invocation_id="withdraw-during-parent-read", recorded_at="2026-10-13T00:01:00+00:00")
        return value

    service.inputs.prepare = withdraw
    value, historical, current = service.read_with_inputs(request.project_id, row["revision_id"])
    assert value["revision"] == row and historical == state.prepared
    assert not value["current_use"]["case_admission_current"] and current is None
    assert len(state.rows) == 2 and state.rows[-1]["status"] == "withdrawn"


def test_parent_read_rechecks_access_after_live_input_verification():
    service, request, state = admission_ports()
    row = approve(service, request)
    prepare = service.inputs.prepare

    def revoke(selection):
        value = prepare(selection)
        state.accessible = False
        return value

    service.inputs.prepare = revoke
    with pytest.raises(SourceAccessDenied):
        service.read_with_inputs(request.project_id, row["revision_id"])


def test_parent_read_rejects_a_corrupt_unselected_predecessor():
    service, request, state = admission_ports()
    row = approve(service, request)
    withdrawn = service.review(request.model_copy(update={"decision": "withdraw", "expected_previous_revision_id": row["revision_id"]}),
        invocation_id="withdraw-original", recorded_at="2026-10-13T00:01:00+00:00")
    state.archives[row["revision_id"]]["request"]["reason"] = "Changed original approval"
    with pytest.raises(CaseApprovalIntegrityError):
        service.read_with_inputs(request.project_id, withdrawn["revision_id"])


def saved_script():
    service, selected, deps, prepared = script_executor()
    admissions, approval, state = admission_ports()
    assert state.prepared == prepared
    row = approve(admissions, approval)
    service.admissions = admissions
    selected = ScriptExecutionSelection.model_validate({**selected.model_dump(mode="json"),
        "case_approval_revision_id": row["revision_id"], "case_approval_artifact_hash": row["artifact_hash"]})
    request = ScriptExecutionRequest.model_validate(service.preview(selected)["request"])
    result = asyncio.run(service.execute(request, invocation_id="verified-parent-script"))
    return service, selected, deps, prepared, admissions, state, result


def test_script_reads_reuse_parents_and_preserve_the_complete_legacy_port_response():
    service, selected, deps, prepared, admissions, state, result = saved_script()
    # The control executes the unchanged independent-read application port.
    service.admissions = SimpleNamespace(read=admissions.read, resolve=admissions.resolve)
    control = service.read(selected.project_id, result["script_revision_id"])
    service.admissions = admissions
    state.calls.clear()

    def no_duplicate_input(*_):
        raise AssertionError("the complete input has already been verified by the admission port")

    service.inputs = SimpleNamespace(prepare=no_duplicate_input, replay=no_duplicate_input)
    value = service.read(selected.project_id, result["script_revision_id"])
    assert value == control and value["result"]["prepared"] == prepared
    assert state.calls == ["historical", "current", "historical", "current"]
    assert deps["provider"].calls == 1 and value["current_use"]["execution_authorized"] is False


@pytest.mark.parametrize("changed", ["mapping", "access"])
def test_script_parent_reuse_does_not_borrow_authority_across_native_archive_reads(changed):
    service, selected, deps, _, _, state, result = saved_script()
    original = service.read(selected.project_id, result["script_revision_id"])
    reader = service.replies.read

    def change_authority(*args):
        value = reader(*args)
        if changed == "mapping":
            state.current = False
        else:
            state.accessible = False
        return value

    service.replies.read = change_authority
    if changed == "access":
        with pytest.raises(SourceAccessDenied):
            service.read(selected.project_id, result["script_revision_id"])
    else:
        value = service.read(selected.project_id, result["script_revision_id"])
        assert value["result"] == original["result"] and value["metadata"] == original["metadata"]
        assert not value["current_use"]["input_current"]
    assert deps["provider"].calls == 1


@pytest.mark.parametrize("fault", ["project", "mapping", "hash", "cases", "digest", "oracle", "missing_live", "live_basis"])
def test_script_parent_port_cannot_substitute_complete_inputs_or_admission(fault):
    service, selected, deps, _, admissions, _, result = saved_script()
    reader = admissions.read_with_inputs
    calls = []

    def substitute(*args):
        value, historical, current = deepcopy(reader(*args))
        calls.append(1)
        if fault in {"missing_live", "live_basis"}:
            if len(calls) == 2:
                if fault == "missing_live":
                    current = None
                else:
                    current["cases"][0]["steps"][0] = "Substituted original step"
                    current["input_digest"] = acceptance_digest({key: item for key, item in current.items() if key != "input_digest"})
        elif fault == "project":
            historical["project_id"] = "other"
        elif fault == "mapping":
            historical["mapping_pin"]["revision_id"] = "other"
        elif fault == "hash":
            historical["mapping_pin"]["artifact_hash"] = acceptance_digest("other")
        elif fault == "cases":
            historical["selected_case_ids"].pop()
        elif fault == "digest":
            historical["input_digest"] = acceptance_digest("other")
        else:
            historical["obligations"][0]["oracle"]["expected_result"] = "Substituted expected behavior"
            historical["input_digest"] = acceptance_digest({key: item for key, item in historical.items() if key != "input_digest"})
        return value, historical, current

    admissions.read_with_inputs = substitute
    with pytest.raises(ValueError):
        service.read(selected.project_id, result["script_revision_id"])
    assert deps["provider"].calls == 1
