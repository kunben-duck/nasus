from copy import deepcopy
import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.api.app.application.quality_loop.automation_inputs import AutomationInputApplicationService, AutomationInputSelection
from apps.api.app.application.quality_loop.test_design_mapping_pins import mapping_generation_pin
from apps.api.app.application.quality_loop.test_design_output import validate_test_design_output
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.automation_input import AutomationInputChanged, AutomationInputInvalid, compile_automation_input
from apps.api.app.domain.quality_loop.test_design_generation import compile_generation_input
from apps.api.app.domain.quality_loop.test_design_mapping import assess_mappings
from apps.api.tests.test_test_design_generation import generation_inputs, case_output
from apps.api.tests.test_test_design_mapping import reviews


def automation_inputs():
    prepared = compile_generation_input(*generation_inputs())
    proposal = validate_test_design_output(prepared, json.dumps(case_output(prepared)))
    result = {"metadata": {"project_id": "p", "generation_id": "g", "artifact_hash": acceptance_digest(proposal)},
        "result": {"context_pin": deepcopy(prepared["context_pin"]), "scope_pin": deepcopy(prepared["scope_pin"]),
            "request": {"input_digest": prepared["input_digest"]}, "proposal": proposal, "status": "draft"},
        "current_use": {"scope_current": True}}
    mapping = {"revision": {"project_id": "p", "revision_id": "m", "artifact_hash": acceptance_digest("mapping"),
        "request_hash": acceptance_digest("review"), "status": "reviewed"}, "generation_pin": deepcopy(mapping_generation_pin(result)),
        "assessment": assess_mappings(proposal, reviews(proposal)),
        "current_use": {"mapping_current": True, "mapping_complete": True}}
    return prepared, result, mapping, tuple(case["case_id"] for case in proposal["cases"])


def test_automation_input_preserves_all_source_oracles_case_steps_and_independent_pins():
    inputs = automation_inputs()
    original = deepcopy(inputs)
    value = compile_automation_input(*inputs)
    assert inputs == original
    assert value["purpose"] == "automation" and value["context_pin"] == inputs[0]["context_pin"]
    assert value["mapping_pin"]["artifact_hash"] == inputs[2]["revision"]["artifact_hash"]
    assert value["cases"] == sorted(inputs[1]["result"]["proposal"]["cases"], key=lambda case: case["case_id"])
    assert value["constraint_denominator"] == 2 and value["obligation_denominator"] == 7
    assert value["required_constraints"] == inputs[0]["context"]["required_constraints"]
    assert value["scope_contract"] == inputs[0]["scope_contract"]
    for row, source in zip(value["obligations"], inputs[0]["obligations"]):
        assert row["oracle"] == source["oracle"] and row["authority"] == source["authority"]
        assert row["selected_case_ids"]
    assert value["readiness"]["status"] == "blocked"
    assert "api_or_dom_locator_evidence_not_bound" in value["readiness"]["reason_codes"]
    assert not value["generation_authorized"] and not value["execution_authorized"]
    assert value["automated_count"] == value["executed_on_target_count"] == value["passed_count"] == 0
    assert value["input_digest"] == acceptance_digest({key: item for key, item in value.items() if key != "input_digest"})
    assert compile_automation_input(*inputs[:-1], tuple(reversed(inputs[-1]))) == value
    value["cases"][0]["steps"].clear()
    assert inputs == original


@pytest.mark.parametrize("change", ["foreign_case", "duplicate_case", "empty", "omit_case", "rejected_case",
    "mapping_incomplete", "project", "generation", "context", "scope", "oracle", "coverage_pass", "denominator"])
def test_automation_input_cannot_replace_or_drop_reviewed_source_obligations(change):
    prepared, result, mapping, ids = automation_inputs()
    if change == "foreign_case":
        ids = (*ids, "foreign-case")
    elif change == "duplicate_case":
        ids = (*ids, ids[0])
    elif change == "empty":
        ids = ()
    elif change == "omit_case":
        ids = ids[1:]
    elif change == "rejected_case":
        mapping["assessment"]["accepted_case_ids"].pop()
    elif change == "mapping_incomplete":
        mapping["current_use"]["mapping_complete"] = False
    elif change == "project":
        mapping["revision"]["project_id"] = "other"
    elif change == "generation":
        mapping["generation_pin"]["generation_id"] = "other"
    elif change in {"context", "scope"}:
        mapping["generation_pin"][change + "_pin"]["artifact_hash"] = acceptance_digest("other")
    elif change == "oracle":
        mapping["assessment"]["coverage"]["rows"][0]["oracle_digest"] = acceptance_digest("other")
    elif change == "coverage_pass":
        mapping["assessment"]["coverage"]["rows"][0]["passed"] = True
    else:
        mapping["assessment"]["coverage"]["rows"].pop()
    with pytest.raises(AutomationInputInvalid):
        compile_automation_input(prepared, result, mapping, ids)


@pytest.mark.parametrize("dependency", ["scope", "mapping"])
def test_historical_inputs_do_not_become_current_automation_authority(dependency):
    prepared, result, mapping, ids = automation_inputs()
    (result if dependency == "scope" else mapping)["current_use"][dependency + "_current"] = False
    with pytest.raises(AutomationInputChanged):
        compile_automation_input(prepared, result, mapping, ids)


def test_over_budget_automation_input_is_rejected_without_top_k_or_truncation(monkeypatch):
    import apps.api.app.domain.quality_loop.automation_input as policy
    monkeypatch.setattr(policy, "MAX_AUTOMATION_INPUT_BYTES", 128)
    with pytest.raises(AutomationInputInvalid, match="no silent truncation"):
        compile_automation_input(*automation_inputs())


def test_automation_selection_rejects_extra_authority_and_implicit_or_duplicate_cases():
    request = {"project_id": "p", "mapping_revision_id": "m", "mapping_artifact_hash": acceptance_digest("m"), "case_ids": ["case"]}
    for changes in ({"case_ids": []}, {"case_ids": ["case", "case"]}, {"case_ids": [True]},
        {"execution_authorized": True}, {"mapping_artifact_hash": "latest"}):
        with pytest.raises(ValidationError):
            AutomationInputSelection.model_validate({**request, **changes})


def test_application_revalidates_all_ports_and_current_access_after_compilation():
    prepared, result, mapping, ids = automation_inputs()
    seen = []
    class Mappings:
        def resolve(self, project, revision, digest):
            seen.append(("mapping", project, revision, digest))
            return deepcopy(mapping)
    class Results:
        def read(self, project, generation):
            seen.append(("result", project, generation))
            return deepcopy(result)
    class Generation:
        def prepare(self, selection):
            seen.append(("scope", selection.scope_revision_id, selection.scope_artifact_hash))
            return deepcopy(prepared)
    class Authorization:
        def scope(self, project):
            return SimpleNamespace(project_id=project)
        def require_current(self, access):
            seen.append(("access", access.project_id))
    service = AutomationInputApplicationService(Mappings(), Results(), Generation(), Authorization())
    request = AutomationInputSelection(project_id="p", mapping_revision_id="m",
        mapping_artifact_hash=mapping["revision"]["artifact_hash"], case_ids=ids)
    assert service.prepare(request) == compile_automation_input(prepared, result, mapping, ids)
    assert seen[:3] == seen[3:6] and seen[-1] == ("access", "p")

    original = service.mappings.resolve
    def withdrawn(*args):
        value = original(*args)
        if len(seen) > 10:
            raise AutomationInputChanged("review withdrawn during preparation")
        return value
    service.mappings.resolve = withdrawn
    with pytest.raises(AutomationInputChanged):
        service.prepare(request)


@pytest.mark.parametrize("failure,code", [(AutomationInputInvalid, "automation_input_incomplete"),
    (AutomationInputChanged, "automation_input_changed")])
def test_typed_automation_errors_are_not_swallowed_by_generic_image_validation(failure, code):
    from fastapi import HTTPException
    from apps.api.app.interface.http.routers.automation_inputs import automation_input_errors
    from apps.api.app.interface.http.routers.image_revisions import revision_errors
    from apps.api.app.interface.http.evidence_errors import evidence_read_errors
    with pytest.raises(HTTPException) as caught:
        with revision_errors(), evidence_read_errors(handle_validation=False), automation_input_errors():
            raise failure("private-cases-and-oracles")
    assert caught.value.status_code == 409 and caught.value.detail["error"]["code"] == code
    assert "private-cases-and-oracles" not in str(caught.value.detail)


@pytest.mark.parametrize("failed", [False, True])
def test_mapping_commit_refreshes_current_private_consumers_without_granting_execution(failed):
    from apps.api.app.application.platform.tool_handlers.test_design_mappings import TestDesignMappingToolHandler
    from apps.api.app.application.quality_loop.test_design_mapping_pins import mapping_review_query_keys
    from apps.api.app.domain.quality_loop.test_design_mapping import MAPPING_TOOL
    emitted = []
    async def emit(*args):
        emitted.append(args)
    def review(request, **kwargs):
        assert request.project_id == "p" and kwargs["invocation_id"] == "command"
        if failed:
            raise AutomationInputChanged("private review error")
        return {"revision_id": "withdrawal"}
    payload = {"project_id": "p", "generation_id": "g", "generation_artifact_hash": acceptance_digest("g"),
        "expected_previous_revision_id": "previous", "decision": "withdraw", "mappings": None, "reason": "Independent withdrawal"}
    handler = TestDesignMappingToolHandler(SimpleNamespace(review=review), SimpleNamespace(emit_tool_status=emit),
        SimpleNamespace(require_invocation_project_scope=lambda invocation: None))
    asyncio.run(handler.handle(SimpleNamespace(id="command", tool_id=MAPPING_TOOL, input_payload=payload)))
    expected = mapping_review_query_keys("p")
    assert emitted[0][3] == [] and emitted[-1][3] == ([] if failed else expected)
    assert ["automation-input", "p"] in expected and all(len(key) == 2 and key[1] == "p" for key in expected)
    assert "private review error" not in emitted[-1][2]
