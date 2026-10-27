"""Public v3 draft/review/plan contracts; no business gold or native target grant."""
import asyncio
from copy import deepcopy
import json

import pytest

from apps.api.app.application.quality_loop.automation_script_inputs import (
    ScriptExecutionRequest, ScriptExecutionSelection, script_messages, validate_script_output,
)
from apps.api.app.application.quality_loop.generation_executor import NativeGenerationReply
from apps.api.app.application.quality_loop.run_plan_inputs import RunPlanSelection
from apps.api.app.application.quality_loop.run_plan_observations import RunPlanObservationApplicationService
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.automation_script_review import assess_script_review
from apps.api.app.domain.quality_loop.automation_scripts import script_http_protocol, validate_script_proposal
from apps.api.app.domain.quality_loop.http_bindings import HTTP_FIXTURE_RECEIPT_SCHEMA
from apps.api.app.domain.quality_loop.run_plan import compile_run_plan, run_plan_artifact_schema
from apps.api.app.domain.quality_loop.run_plan_build import compile_run_plan_build
from apps.api.app.domain.quality_loop.run_plan_observations import compile_case_jobs, verify_plan
from apps.api.tests.test_automation_scripts import script_executor, script_output
from apps.api.tests.test_automation_script_reviews import decisions
from apps.api.tests.test_run_plans import plan_inputs, selection_for


def fixture_script_output(prepared):
    output = script_output(prepared, kind="http")
    for script in output["scripts"]:
        script["actions"].insert(0, {"action": "use_fixture_binding", "binding_id": "session", "source_step_indices": [0]})
        for action in script["actions"]:
            if action["action"] == "request":
                action["path"] = "/sessions/{{session}}"
        for item in script["assertions"]:
            item["action_index"] += 1
    return output


def fixture_plan_inputs():
    _, _, sources, _ = plan_inputs()
    app, original_selection, deps, prepared = script_executor()
    selection = ScriptExecutionSelection.model_validate({**original_selection.model_dump(mode="json"),
        "http_protocol": HTTP_FIXTURE_RECEIPT_SCHEMA})

    async def generate(system, content, model, **kwargs):
        assert json.loads(content) == prepared
        return NativeGenerationReply(json.dumps(fixture_script_output(prepared)), 123, 45, "provider")

    deps["provider"].generate = generate
    request = ScriptExecutionRequest.model_validate(app.preview(selection)["request"])
    metadata = asyncio.run(app.execute(request, invocation_id="new-fixture-generation"))
    draft = app.read("p", metadata["script_revision_id"])
    proposal = draft["result"]["proposal"]
    actions, assertions = decisions(proposal)
    review = {"revision": {"revision_id": "new-fixture-review", "project_id": prepared["project_id"],
        "artifact_hash": acceptance_digest([actions, assertions]), "request_hash": acceptance_digest("new-independent-review"),
        "authority_actor": "independent-fixture-reviewer", "status": "reviewed",
        "script_revision_id": draft["metadata"]["script_revision_id"], "script_artifact_hash": draft["metadata"]["artifact_hash"]},
        "assessment": assess_script_review(proposal, actions, assertions)}
    selection = selection_for(draft, review, sources).model_dump(mode="json")
    selection["policy_revision"] = "nasus.run-plan.v3"
    return draft, review, sources, selection


def fixture_build_inputs():
    from apps.api.app.application.quality_loop.run_plan_build_inputs import RunPlanBuildSelection
    from apps.api.tests.test_run_plan_builds import binding_inputs
    view, selected, builds = binding_inputs()
    draft, review, sources, selection = fixture_plan_inputs()
    assert view["artifact"]["plan"]["source_pin"] == sources
    selection["target_build"] = deepcopy(view["artifact"]["plan"]["selection"]["target_build"])
    view["artifact"]["schema"] = "nasus.run-plan-artifact.v3"
    view["artifact"]["plan"] = compile_run_plan(draft, review, selection, sources)
    view["metadata"]["artifact_hash"] = acceptance_digest(view["artifact"])
    selected = RunPlanBuildSelection.model_validate({**selected.model_dump(mode="json"),
        "run_plan_artifact_hash": view["metadata"]["artifact_hash"]})
    return view, selected, builds


def test_explicit_imports_preserve_the_complete_original_case_step_oracle_denominator():
    _, _, _, prepared = script_executor()
    original = deepcopy(prepared)
    output = fixture_script_output(prepared)
    proposal = validate_script_output(prepared, json.dumps(output), http_protocol=HTTP_FIXTURE_RECEIPT_SCHEMA)
    assert prepared == original and script_http_protocol(proposal) == HTTP_FIXTURE_RECEIPT_SCHEMA
    assert proposal["case_count"] == len(original["cases"]) and not proposal["gaps"]
    for case, script in zip(original["cases"], proposal["scripts"]):
        assert script["case_digest"] == acceptance_digest(case)
        assert script["actions"][0]["action"] == "use_fixture_binding"
        assert len(script["assertions"]) == len(case["assertions"])
        assert all(item["oracle"] == saved["oracle"] and item["oracle_digest"] == saved["oracle_digest"]
            for item, saved in zip(script["assertions"], case["assertions"]))
    assert not proposal["execution_authorized"]
    assert proposal["automated_count"] == proposal["executed_on_target_count"] == proposal["passed_count"] == 0


def test_versioned_consent_complete_native_reply_archive_and_no_second_model_call():
    app, selection, deps, prepared = script_executor()
    old = app.preview(selection)
    selection = ScriptExecutionSelection.model_validate({**selection.model_dump(mode="json"), "http_protocol": HTTP_FIXTURE_RECEIPT_SCHEMA})
    preview = app.preview(selection)
    assert preview["request"]["execution"]["plan_digest"] != old["request"]["execution"]["plan_digest"]
    assert preview["request"]["input_digest"] == old["request"]["input_digest"]
    assert "http_protocol" not in old["request"]
    calls = []

    async def generate(system, content, model, **kwargs):
        calls.append(True)
        assert "use_fixture_binding(binding_id)" in system and HTTP_FIXTURE_RECEIPT_SCHEMA in system
        assert json.loads(content) == prepared
        return NativeGenerationReply(json.dumps(fixture_script_output(prepared)), 123, 45, "provider")

    deps["provider"].generate = generate
    request = ScriptExecutionRequest.model_validate(preview["request"])
    metadata = asyncio.run(app.execute(request, invocation_id="new-fixture-generation"))
    archived = app.read("p", metadata["script_revision_id"])
    assert archived["result"]["proposal"]["schema"] == "nasus.automation-script-proposal.v3"
    assert archived["result"]["request"]["http_protocol"] == HTTP_FIXTURE_RECEIPT_SCHEMA
    assert asyncio.run(app.execute(request, invocation_id="new-fixture-generation")) == metadata and len(calls) == 1
    assert "use_fixture_binding" not in script_messages(prepared)[0]


@pytest.mark.parametrize("fault", ["v1", "v2", "binding_id", "extra_value", "extra_request", "missing_indices",
    "boolean_index", "duplicate_import", "forward_import", "undeclared_path", "partial_path", "query_path",
    "import_as_oracle", "changed_oracle", "missing_oracle", "extra_assertion", "browser_import", "too_many_imports"])
def test_import_drafts_reject_unversioned_or_forged_actions_without_changing_original_obligations(fault):
    _, _, _, prepared = script_executor()
    output = fixture_script_output(prepared)
    script, protocol = output["scripts"][0], HTTP_FIXTURE_RECEIPT_SCHEMA
    imported = script["actions"][0]
    if fault in {"v1", "v2"}: protocol = "nasus.runner-http-execution." + fault
    elif fault == "binding_id": imported["binding_id"] = "session/unsafe"
    elif fault == "extra_value": imported["value"] = "forged-resource"
    elif fault == "extra_request": imported["request_id"] = "forged-setup"
    elif fault == "missing_indices": imported.pop("source_step_indices")
    elif fault == "boolean_index": imported["source_step_indices"] = [True]
    elif fault == "duplicate_import": script["actions"].append(deepcopy(imported))
    elif fault == "forward_import": script["actions"][0], script["actions"][1] = script["actions"][1], script["actions"][0]
    elif fault == "undeclared_path": script["actions"][1]["path"] = "/sessions/{{another}}"
    elif fault == "partial_path": script["actions"][1]["path"] = "/sessions/id-{{session}}"
    elif fault == "query_path": script["actions"][1]["path"] = "/sessions?id={{session}}"
    elif fault == "import_as_oracle": script["assertions"][0]["action_index"] = 0
    elif fault == "changed_oracle": script["assertions"][0]["oracle"]["expected_result"] = "invented"
    elif fault == "missing_oracle": script["assertions"].pop()
    elif fault == "extra_assertion": script["actions"].append(deepcopy(script["actions"][-1]))
    elif fault == "browser_import": script["kind"] = "browser"
    elif fault == "too_many_imports":
        script["actions"] += [{**imported, "binding_id": "resource" + str(index)} for index in range(16)]
    with pytest.raises(ValueError):
        validate_script_output(prepared, json.dumps(output), http_protocol=protocol)


def test_fixture_import_is_independently_reviewed_and_the_plan_keeps_the_full_original_input():
    draft, review, sources, selection = fixture_plan_inputs()
    original = deepcopy((draft, review, sources, selection))
    plan = compile_run_plan(draft, review, RunPlanSelection.model_validate(selection).model_dump(mode="json"), sources)
    assert (draft, review, sources, selection) == original
    assert verify_plan(plan) == plan and plan["schema"] == "nasus.run-plan.v3"
    assert run_plan_artifact_schema(plan["schema"]) == "nasus.run-plan-artifact.v3"
    jobs = compile_case_jobs(plan, run_id="original-case-attempt", timeout_ms=3000)
    assert [job["us_id"] for job in jobs] == plan["prepared"]["selected_case_ids"]
    assert all(job["receipt_protocol"] == HTTP_FIXTURE_RECEIPT_SCHEMA for job in jobs)
    assert not plan["execution_authorized"] and not review["assessment"]["execution_authorized"]
    assert plan["automated_count"] == plan["executed_on_target_count"] == plan["passed_count"] == 0
    actions, assertions = decisions(plan["proposal"])
    actions.pop(0)
    with pytest.raises(ValueError): assess_script_review(plan["proposal"], actions, assertions)


@pytest.mark.parametrize("fault", ["v1_policy", "v2_policy", "old_review", "changed_import"])
def test_new_protocol_cannot_adopt_an_old_plan_policy_or_independent_review(fault):
    draft, review, sources, selection = fixture_plan_inputs()
    if fault == "v1_policy": selection["policy_revision"] = "nasus.run-plan.v1"
    elif fault == "v2_policy": selection["policy_revision"] = "nasus.run-plan.v2"
    elif fault == "old_review": review["revision"]["script_artifact_hash"] = acceptance_digest("old-reviewed-script")
    else: draft["result"]["proposal"]["scripts"][0]["actions"][0]["binding_id"] = "another"
    with pytest.raises(ValueError): compile_run_plan(draft, review, selection, sources)


def test_template_commands_cannot_dispatch_without_original_setup_handoff():
    draft, review, sources, selection = fixture_plan_inputs()
    plan = compile_run_plan(draft, review, selection, sources)
    with pytest.raises(ValueError, match="original setup handoff"):
        RunPlanObservationApplicationService(None).commands(plan, run_id="original-case-attempt", timeout_ms=3000)


@pytest.mark.parametrize("schema", [[], {}, None, True, "nasus.automation-script-proposal.v4"])
def test_protocol_selector_rejects_invalid_versions_as_bounded_domain_errors(schema):
    with pytest.raises(ValueError, match="explicitly versioned"):
        script_http_protocol({"schema": schema, "http_protocol": HTTP_FIXTURE_RECEIPT_SCHEMA})


def test_v3_build_binding_retains_the_complete_original_code_inventory_without_execution_authority():
    view, selection, builds = fixture_build_inputs()
    originals = deepcopy((view, builds))
    binding = compile_run_plan_build(view, selection.model_dump(mode="json"), builds)
    assert (view, builds) == originals
    assert binding["plan_digest"] == view["artifact"]["plan"]["plan_digest"]
    assert binding["run_plan_artifact_hash"] == selection.run_plan_artifact_hash
    assert not binding["execution_authorized"] and binding["passed_count"] == 0


def test_v3_without_original_setup_handoff_is_rejected_before_lease_claim_or_dispatch():
    from apps.api.app.application.quality_loop.run_plan_case_execution import RunPlanCaseExecutionApplicationService
    from apps.api.tests.test_run_plan_case_execution import inputs
    draft, review, sources, selection = fixture_plan_inputs()
    plan, scope, _, _ = inputs(compile_run_plan(draft, review, selection, sources))

    class NoSideEffects:
        def __getattr__(self, name):
            raise AssertionError("no lease, claim, native runner, archive or outcome before original handoff")

    service = RunPlanCaseExecutionApplicationService(NoSideEffects(), NoSideEffects(), NoSideEffects(), NoSideEffects())
    with pytest.raises(ValueError, match="original setup handoff before claim"):
        asyncio.run(service.execute(plan, scope, require_current=lambda: None))
