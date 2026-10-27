"""Actual PG/MinIO late revocation; model and oracle content are specimens."""
import pytest

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_automation_scripts_api import (
    native_scripts, mapping, generation_result, design_scope, publication, documents, evidence_api, base_evidence_api,
    run_confirmed, read_draft, completed, grant_member, restrict_source,
)
from apps.api.tests.test_case_approvals_api import admission, submit, read


def test_actual_source_revocation_after_admission_parent_rejects_script_read(native_scripts, monkeypatch):
    v = native_scripts
    _, response = run_confirmed(v)
    command = completed(response)
    original = read_draft(v, command).json()
    grant_member(v)
    service = v["script_service"]
    reader = service.admissions.read_with_inputs
    calls = []

    def revoke(*args):
        value = reader(*args)
        calls.append(1)
        if len(calls) == 1:
            restrict_source(v)
        return value

    monkeypatch.setattr(service.admissions, "read_with_inputs", revoke)
    with actor_scope(UserProfile.model_validate(v["member"])), pytest.raises(SourceAccessDenied):
        service.read(v["project_id"], original["metadata"]["script_revision_id"])
    assert len(calls) == 1 and len(v["script_calls"]) == 1
    monkeypatch.setattr(service.admissions, "read_with_inputs", reader)
    assert read_draft(v, command).json() == original


def test_actual_case_head_withdrawal_during_parent_read_cannot_return_live_input(admission, monkeypatch):
    v = admission
    command = completed(submit(v))
    original = read(v, command).json()
    service = v["admission_service"]
    prepare = service.inputs.prepare
    withdrawn = []

    def withdraw(selection):
        value = prepare(selection)
        if not withdrawn:
            withdrawn.append(completed(submit(v, {**v["admission_request"], "decision": "withdraw",
                "expected_previous_revision_id": original["revision"]["revision_id"]})))
        return value

    monkeypatch.setattr(service.inputs, "prepare", withdraw)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        value, historical, current = service.read_with_inputs(v["project_id"], original["revision"]["revision_id"])
    assert value["revision"] == original["revision"] and value["basis"] == original["basis"]
    assert historical == v["admission_preview"]["prepared"] and current is None
    assert not value["current_use"]["case_admission_current"]
    assert len(withdrawn) == 1 and read(v, withdrawn[0]).json()["revision"]["status"] == "withdrawn"
