"""Case admission consumption specimens, not target execution or business gold."""
import asyncio
from copy import deepcopy

import pytest

from apps.api.app.application.quality_loop.automation_script_inputs import ScriptExecutionRequest, ScriptExecutionSelection
from apps.api.app.domain.quality_loop.case_approval import CaseApprovalChanged, CaseApprovalIntegrityError, case_approval_basis, case_approval_cohort
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.tests.test_automation_scripts import script_executor


def admitted_executor():
    service, selected, deps, prepared = script_executor()
    basis = case_approval_basis(prepared)
    revision_id, artifact_hash = "explicit-case-admission", acceptance_digest("explicit-admission-specimen")
    value = {"revision": {"revision_id": revision_id, "artifact_hash": artifact_hash, "status": "approved",
        "project_id": selected.project_id, "generation_id": prepared["generation_pin"]["generation_id"],
        "mapping_revision_id": selected.mapping_revision_id, "input_digest": prepared["input_digest"],
        "cohort_id": case_approval_cohort(basis), "case_count": len(prepared["cases"])}, "basis": basis,
        "current_use": {"case_admission_current": True}}

    class Admissions:
        def __init__(self): self.value = deepcopy(value); self.reads = []; self.resolves = []; self.stale = False
        def read(self, project, revision):
            self.reads.append((project, revision))
            return deepcopy(self.value)
        def resolve(self, project, revision, digest, actual):
            self.resolves.append((project, revision, digest, deepcopy(actual)))
            if self.stale:
                raise CaseApprovalChanged("explicit admission withdrawal specimen")
            return deepcopy(self.value)

    service.admissions = Admissions()
    selected = ScriptExecutionSelection.model_validate({**selected.model_dump(mode="json"),
        "case_approval_revision_id": revision_id, "case_approval_artifact_hash": artifact_hash})
    return service, selected, deps, prepared


def test_new_script_preview_rejects_unapproved_input_without_egress_or_reservation():
    service, selected, deps, _ = script_executor()
    legacy = ScriptExecutionSelection.model_validate({key: value for key, value in selected.model_dump(mode="json").items()
        if not key.startswith("case_approval_")})
    with pytest.raises(CaseApprovalChanged):
        service.preview(legacy)
    assert deps["provider"].calls == 0 and deps["repository"].stored is None


def test_script_admission_pins_must_be_supplied_as_a_complete_pair():
    _, selected, _, _ = script_executor()
    legacy = {key: value for key, value in selected.model_dump(mode="json").items() if not key.startswith("case_approval_")}
    assert not any(key.startswith("case_approval_") for key in ScriptExecutionSelection.model_validate(legacy).model_dump(mode="json"))
    for key, value in (("case_approval_revision_id", "admission"), ("case_approval_artifact_hash", acceptance_digest("admission"))):
        with pytest.raises(ValueError):
            ScriptExecutionSelection.model_validate({**legacy, key: value})


def test_preview_and_every_live_recheck_preserve_the_original_admission_and_all_cases():
    service, selected, deps, prepared = admitted_executor()
    preview = service.preview(selected)
    assert preview["request"]["case_approval_revision_id"] == selected.case_approval_revision_id
    assert preview["request"]["case_approval_artifact_hash"] == selected.case_approval_artifact_hash
    assert service.admissions.resolves[-1][3] == prepared
    assert preview["request"]["input_digest"] == prepared["input_digest"]
    assert deps["provider"].calls == 0 and deps["repository"].stored is None
    request = ScriptExecutionRequest.model_validate(preview["request"])
    result = asyncio.run(service.execute(request, invocation_id="admitted-script"))
    archive = service.read(selected.project_id, result["script_revision_id"])
    assert archive["result"]["prepared"] == prepared and archive["current_use"]["input_current"] is True
    assert len(service.admissions.resolves) >= 4 and deps["provider"].calls == 1
    assert archive["result"]["proposal"]["automated_count"] == archive["result"]["proposal"]["passed_count"] == 0


@pytest.mark.parametrize("fault", ["revision", "hash", "project", "generation", "mapping", "input", "cohort", "count", "status", "basis", "current"])
def test_a_port_response_cannot_substitute_admission_oracles_or_current_authority(fault):
    service, selected, deps, _ = admitted_executor()
    value = service.admissions.value
    fields = {"revision": "revision_id", "hash": "artifact_hash", "project": "project_id", "generation": "generation_id",
        "mapping": "mapping_revision_id", "input": "input_digest", "cohort": "cohort_id", "count": "case_count", "status": "status"}
    if fault in fields:
        value["revision"][fields[fault]] = 1 if fault == "count" else "substituted"
    elif fault == "basis":
        value["basis"]["obligation_pins"][0]["oracle_digest"] = acceptance_digest("different-business-oracle")
    else:
        value["current_use"]["case_admission_current"] = False
    with pytest.raises((CaseApprovalChanged, CaseApprovalIntegrityError)):
        service.preview(selected)
    assert deps["provider"].calls == 0 and deps["repository"].stored is None


def test_withdrawal_before_model_egress_rejects_the_original_confirmation():
    service, selected, deps, _ = admitted_executor()
    request = ScriptExecutionRequest.model_validate(service.preview(selected)["request"])
    service.admissions.stale = True
    with pytest.raises(CaseApprovalChanged):
        asyncio.run(service.execute(request, invocation_id="withdrawn-before-egress"))
    assert deps["provider"].calls == 0 and deps["repository"].stored is None


def test_withdrawal_after_egress_preserves_reservation_and_never_resends_unknown_reply():
    service, selected, deps, _ = admitted_executor()
    request = ScriptExecutionRequest.model_validate(service.preview(selected)["request"])
    original = deps["provider"].generate

    async def withdraw(*args, **kwargs):
        reply = await original(*args, **kwargs)
        service.admissions.stale = True
        return reply

    deps["provider"].generate = withdraw
    with pytest.raises(CaseApprovalChanged):
        asyncio.run(service.execute(request, invocation_id="withdrawn-after-egress"))
    assert deps["provider"].calls == 1 and deps["repository"].stored["reply"] is None and deps["repository"].stored["result"] is None
    with pytest.raises(CaseApprovalChanged):
        asyncio.run(service.execute(request, invocation_id="withdrawn-after-egress"))
    assert deps["provider"].calls == 1


def test_withdrawal_does_not_rewrite_archived_script_or_upgrade_old_approval():
    service, selected, deps, _ = admitted_executor()
    request = ScriptExecutionRequest.model_validate(service.preview(selected)["request"])
    result = asyncio.run(service.execute(request, invocation_id="historical-admitted-script"))
    original = service.read(selected.project_id, result["script_revision_id"])
    service.admissions.stale = True
    historical = service.read(selected.project_id, result["script_revision_id"])
    assert historical["result"] == original["result"] and historical["metadata"] == original["metadata"]
    assert historical["historical_not_live"] is True and historical["current_use"]["input_current"] is False
    assert deps["provider"].calls == 1
