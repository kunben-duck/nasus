"""Explicit version migration specimens, not approved exweb business behavior."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from apps.api.app.application.quality_loop.automation_script_inputs import ScriptExecutionRequest, ScriptExecutionSelection, script_messages, validate_script_output
from apps.api.app.application.quality_loop.generation_executor import NativeGenerationReply
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.automation_script_review import assess_script_review
from apps.api.app.domain.quality_loop.automation_scripts import validate_script_proposal, script_http_protocol
from apps.api.app.domain.quality_loop.http_bindings import HTTP_BINDING_RECEIPT_SCHEMA
from apps.api.app.domain.quality_loop.run_plan import compile_run_plan
from apps.api.app.domain.quality_loop.run_plan_observations import RunPlanObservationInvalid
from apps.api.tests.test_automation_scripts import script_executor, script_output
from apps.api.tests.test_automation_script_reviews import decisions
from apps.api.tests.test_run_plans import plan_inputs, selection_for
from apps.api.tests.test_run_plan_observations import observation_service


def binding_script_output(prepared):
    output = script_output(prepared, kind="http")
    for script in output["scripts"]:
        prefix = [dict(action="request", request_id="create", method="POST", path="/sessions", headers_json="{}",
            body_json='{"title":"Independent local transport fixture"}', source_step_indices=[0]),
            dict(action="capture_json", request_id="create", pointer="/sessionId", binding_id="session", source_step_indices=[0])]
        for action in script["actions"]:
            if action["action"] == "request":
                action["path"] = "/sessions/{{session}}"
        script["actions"] = prefix + script["actions"]
        for assertion in script["assertions"]:
            assertion["action_index"] += len(prefix)
    return output


def binding_plan_inputs(base_url="http://127.0.0.1:19876"):
    draft, review, sources, _ = plan_inputs()
    prepared = draft["result"]["prepared"]
    proposal = validate_script_proposal(prepared, binding_script_output(prepared), http_protocol=HTTP_BINDING_RECEIPT_SCHEMA)
    draft["result"]["proposal"] = proposal
    draft["metadata"]["artifact_hash"] = acceptance_digest(draft["result"])
    review["revision"]["script_artifact_hash"] = draft["metadata"]["artifact_hash"]
    actions, assertions = decisions(proposal)
    review["assessment"] = assess_script_review(proposal, actions, assertions)
    selection = selection_for(draft, review, sources).model_dump(mode="json")
    selection["policy_revision"] = "nasus.run-plan.v2"
    selection["environment"]["base_url"] = base_url
    return draft, review, sources, selection


def binding_plan(base_url="http://127.0.0.1:19876"):
    draft, review, sources, selection = binding_plan_inputs(base_url)
    return compile_run_plan(draft, review, selection, sources)


def test_old_request_and_prompt_remain_identical_without_new_null_fields():
    service, selection, _, prepared = script_executor()
    original = selection.model_dump(mode="json")
    assert "http_protocol" not in original
    request = service.preview(selection)["request"]
    assert "http_protocol" not in request
    assert ScriptExecutionRequest.model_validate(request).model_dump(mode="json") == request
    assert ScriptExecutionSelection.model_validate(original).model_dump(mode="json") == original
    assert script_messages(prepared) == script_messages(prepared, http_protocol="nasus.runner-http-execution.v1")
    assert "capture_json" not in script_messages(prepared)[0]
    with pytest.raises(ValueError):
        validate_script_output(prepared, json.dumps(binding_script_output(prepared)))


def test_version_changes_consent_and_archived_reply_replay_without_resending():
    service, selection, deps, prepared = script_executor()
    old = service.preview(selection)
    selection = ScriptExecutionSelection.model_validate({**selection.model_dump(mode="json"), "http_protocol": HTTP_BINDING_RECEIPT_SCHEMA})
    preview = service.preview(selection)
    assert preview["request"]["execution"]["plan_digest"] != old["request"]["execution"]["plan_digest"]
    assert preview["request"]["input_digest"] == old["request"]["input_digest"]
    calls = []
    async def generate(system, content, model, **kwargs):
        calls.append(True)
        assert "capture_json" in system and json.loads(content) == prepared
        return NativeGenerationReply(json.dumps(binding_script_output(prepared)), 123, 45, "provider")
    deps["provider"].generate = generate
    request = ScriptExecutionRequest.model_validate(preview["request"])
    value = asyncio.run(service.execute(request, invocation_id="binding-protocol-command"))
    archived = service.read("p", value["script_revision_id"])
    assert archived["result"]["proposal"]["schema"] == "nasus.automation-script-proposal.v2"
    assert archived["result"]["request"]["http_protocol"] == HTTP_BINDING_RECEIPT_SCHEMA
    assert script_http_protocol(archived["result"]["proposal"]) == HTTP_BINDING_RECEIPT_SCHEMA
    assert asyncio.run(service.execute(request, invocation_id="binding-protocol-command")) == value and len(calls) == 1
    stored = deps["results"].bodies[value["artifact_hash"]]
    stored["request"].pop("http_protocol")
    with pytest.raises(ValueError): service.read("p", value["script_revision_id"])


@pytest.mark.parametrize("fault", ["forward_binding", "duplicate_binding", "query_binding", "partial_path", "header",
    "missing_source_step", "capture_as_oracle", "oracle_change", "extra_assertion", "capture_in_browser", "unknown_protocol"])
def test_binding_proposal_cannot_replace_original_steps_or_independent_oracles(fault):
    _, _, _, prepared = script_executor()
    output = binding_script_output(prepared)
    script, protocol = output["scripts"][0], HTTP_BINDING_RECEIPT_SCHEMA
    capture = script["actions"][1]
    if fault == "forward_binding": script["actions"][0]["path"] = "/sessions/{{session}}"
    elif fault == "duplicate_binding": script["actions"].append(deepcopy(capture))
    elif fault == "query_binding": script["actions"][2]["path"] = "/sessions?id={{session}}"
    elif fault == "partial_path": script["actions"][2]["path"] = "/sessions/id-{{session}}"
    elif fault == "header": script["actions"][0]["headers_json"] = '{"Authorization":"unsafe"}'
    elif fault == "missing_source_step": capture["source_step_indices"] = []
    elif fault == "capture_as_oracle": script["assertions"][0]["action_index"] = 1
    elif fault == "oracle_change": script["assertions"][0]["oracle"]["expected_result"] = "invented"
    elif fault == "extra_assertion": script["actions"].append(deepcopy(script["actions"][-1]))
    elif fault == "capture_in_browser": script["kind"] = "browser"
    else: protocol = "future"
    with pytest.raises(ValueError): validate_script_output(prepared, json.dumps(output), http_protocol=protocol)


@pytest.mark.parametrize("operand", [
    '{"title":"first","title":"second"}',
    '{"title":"first","\\u0074itle":"second"}',
    '[{"name":"first","name":"second"}]',
    '{"id":9007199254740993}',
    '{"id":9.007199254740993e15}',
    '{"id":1e400}',
    '{"value":0.' + '1' * 255 + '}',
    '[' * 65 + 'null' + ']' * 65,
])
def test_binding_json_operands_reject_ambiguous_or_unrepresentable_values(operand):
    _, _, _, prepared = script_executor()
    output = binding_script_output(prepared)
    output["scripts"][0]["actions"][0]["body_json"] = operand
    with pytest.raises(ValueError):
        validate_script_output(prepared, json.dumps(output), http_protocol=HTTP_BINDING_RECEIPT_SCHEMA)


def test_binding_json_operands_keep_distinct_objects_and_original_decimal_text():
    _, _, _, prepared = script_executor()
    output = binding_script_output(prepared)
    body = '{"items":[{"id":9007199254740991},{"id":-9007199254740991},{"id":0.1234567890123456789}]}'
    output["scripts"][0]["actions"][0]["body_json"] = body
    proposal = validate_script_output(prepared, json.dumps(output), http_protocol=HTTP_BINDING_RECEIPT_SCHEMA)
    assert proposal["scripts"][0]["actions"][0]["body_json"] == body


@pytest.mark.parametrize("field,operand", [
    ("headers_json", '{"Accept":"application/json","Accept":"text/plain"}'),
    ("headers_json", '{"Accept":"application/json","\\u0041ccept":"text/plain"}'),
    ("value_json", '{"status":200,"status":400}'),
    ("value_json", '9007199254740993'),
])
def test_binding_headers_and_json_oracles_reject_ambiguous_operands(field, operand):
    _, _, _, prepared = script_executor()
    output = binding_script_output(prepared)
    script = output["scripts"][0]
    if field == "headers_json":
        script["actions"][0][field] = operand
    else:
        assertion = script["assertions"][0]
        original = script["actions"][assertion["action_index"]]
        script["actions"][assertion["action_index"]] = dict(action="assert_json", request_id=original["request_id"],
            pointer="/status", value_json=operand, source_step_indices=original["source_step_indices"])
    with pytest.raises(ValueError):
        validate_script_output(prepared, json.dumps(output), http_protocol=HTTP_BINDING_RECEIPT_SCHEMA)


def test_capture_requires_an_independent_action_review_and_never_counts_as_an_oracle():
    plan = binding_plan()
    proposal = plan["proposal"]
    actions, assertions = decisions(proposal)
    reviewed = assess_script_review(proposal, actions, assertions)
    assert reviewed["review_complete"]
    assert reviewed["reviewed_oracle_count"] == sum(len(case["assertions"]) for case in plan["prepared"]["cases"])
    capture_decision = next(item for item in actions if item["action_index"] == 1)
    with pytest.raises(ValueError): assess_script_review(proposal, [item for item in actions if item is not capture_decision], assertions)
    capture_decision["decision"] = "defer"
    assert not assess_script_review(proposal, actions, assertions)["review_complete"]
    assert reviewed["automated_count"] == reviewed["executed_on_target_count"] == reviewed["passed_count"] == 0


@pytest.mark.parametrize("fault", ["plan_downgrade", "proposal_downgrade", "protocol_missing", "protocol_changed", "capture_changed"])
def test_rehashed_version_changes_cannot_reinterpret_a_reviewed_plan(fault):
    plan = binding_plan()
    if fault == "plan_downgrade": plan["selection"]["policy_revision"] = plan["schema"] = "nasus.run-plan.v1"
    elif fault == "proposal_downgrade": plan["proposal"]["schema"] = "nasus.automation-script-proposal.v1"
    elif fault == "protocol_missing": plan["proposal"].pop("http_protocol")
    elif fault == "protocol_changed": plan["proposal"]["http_protocol"] = "future"
    else: plan["proposal"]["scripts"][0]["actions"][1]["binding_id"] = "other"
    plan["script_pin"]["proposal_hash"] = acceptance_digest(plan["proposal"])
    plan["plan_digest"] = acceptance_digest({key: value for key, value in plan.items() if key != "plan_digest"})
    with pytest.raises(RunPlanObservationInvalid): observation_service().commands(plan, run_id="attempt", timeout_ms=5000)


def test_plan_commands_preserve_explicit_version_and_all_original_provenance():
    plan = binding_plan()
    original = deepcopy(plan)
    commands = observation_service().commands(plan, run_id="attempt", timeout_ms=5000)
    for case, command in zip(plan["prepared"]["cases"], commands):
        assert command.http_protocol == HTTP_BINDING_RECEIPT_SCHEMA
        assert command.metadata["case_digest"] == acceptance_digest(case)
        script = next(s for s in plan["proposal"]["scripts"] if s["case_id"] == case["case_id"])
        assert command.steps == tuple(script["actions"])
    assert plan == original and plan["schema"] == "nasus.run-plan.v2"
    command = replace(commands[0], http_protocol="nasus.runner-http-execution.v1")
    with pytest.raises(ValueError):
        from apps.api.app.infrastructure.runner.request_wire import runner_request_body
        runner_request_body(command)
