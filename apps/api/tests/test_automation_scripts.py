"""Explicit DSL/transport specimens, not business-approved target scripts."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.automation_script_inputs import ScriptExecutionSelection, ScriptExecutionRequest, script_messages, validate_script_output
from apps.api.app.application.quality_loop.automation_script_generation import AutomationScriptGenerationApplicationService
from apps.api.app.application.quality_loop.generation_executor import GenerationOutcomeUnknown, NativeGenerationReply
from apps.api.app.domain.quality_loop.automation_input import compile_automation_input
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.automation_scripts import validate_script_proposal
from apps.api.tests.test_automation_input import automation_inputs
from apps.api.tests.test_generation_executor import executor as generation_executor, budget


def script_output(prepared, *, kind="browser"):
    scripts = []
    for case in prepared["cases"]:
        actions = [{"action": "request", "request_id": f"fixture_{index}", "method": "GET",
            "path": "/explicit-protocol-fixture", "headers_json": "{}", "body_json": "null",
            "source_step_indices": [index]} if kind == "http" else {"action": "wait_for", "selector": "#explicit-protocol-fixture",
            "source_step_indices": [index]} for index in range(len(case["steps"]))]
        assertions = []
        for original in case["assertions"]:
            assertions.append({"row_id": original["row_id"], "oracle": deepcopy(original["oracle"]),
                "oracle_digest": original["oracle_digest"], "source_step_index": original["step_index"], "action_index": len(actions)})
            actions.append({"action": "assert_body", "request_id": f"fixture_{original['step_index']}",
                "value": original["oracle"]["expected_result"], "source_step_indices": [original["step_index"]]} if kind == "http" else {
                "action": "assert_text", "selector": "#explicit-protocol-fixture", "value": original["oracle"]["expected_result"],
                "source_step_indices": [original["step_index"]]})
        scripts.append({"case_id": case["case_id"], "case_digest": acceptance_digest(case), "kind": kind, "actions": actions, "assertions": assertions})
    return {"input_digest": prepared["input_digest"], "scripts": scripts, "gaps": []}


def test_script_drafts_preserve_all_cases_steps_oracles_and_do_not_grant_execution():
    prepared = compile_automation_input(*automation_inputs())
    output = script_output(prepared)
    originals = deepcopy((prepared, output))
    proposal = validate_script_output(prepared, json.dumps(output))
    assert (prepared, output) == originals
    assert proposal["script_count"] == proposal["case_count"] == len(prepared["cases"])
    assert proposal["gap_count"] == 0 and proposal["review_status"] == "pending_independent_review"
    assert proposal["automated_count"] == proposal["executed_on_target_count"] == proposal["passed_count"] == 0
    assert proposal["execution_authorized"] is False
    assert json.loads(script_messages(prepared)[1]) == prepared
    assert "untrusted evidence" in script_messages(prepared)[0]


@pytest.mark.parametrize("fault", ["input_digest", "case_digest", "missing_case", "duplicate_case", "foreign_case", "missing_step",
    "foreign_step", "boolean_step", "missing_oracle", "oracle_value", "oracle_digest", "oracle_step", "action_index",
    "boolean_action_index", "non_assertion_binding", "unbound_assertion", "script_code", "action_operand", "empty_selector",
    "absolute_url", "network_path", "url_backslash", "gap_duplicate", "gap_digest", "authority", "coverage"])
def test_draft_validation_rejects_unpinned_or_forged_scripts(fault):
    prepared = compile_automation_input(*automation_inputs())
    output = script_output(prepared)
    script = output["scripts"][0]
    assertion = script["assertions"][0]
    if fault == "input_digest": output["input_digest"] = acceptance_digest("other")
    elif fault == "case_digest": script["case_digest"] = acceptance_digest("other")
    elif fault == "missing_case": output["scripts"].pop()
    elif fault == "duplicate_case": output["scripts"].append(deepcopy(script))
    elif fault == "foreign_case": script["case_id"] = "foreign"
    elif fault == "missing_step":
        case = prepared["cases"][0]
        case["steps"].append("Another original step")
        prepared["input_digest"] = acceptance_digest({key: value for key, value in prepared.items() if key != "input_digest"})
        output["input_digest"] = prepared["input_digest"]
        script["case_digest"] = acceptance_digest(case)
    elif fault == "foreign_step": script["actions"][0]["source_step_indices"] = [63]
    elif fault == "boolean_step": script["actions"][0]["source_step_indices"] = [True]
    elif fault == "missing_oracle": script["assertions"].pop()
    elif fault == "oracle_value": assertion["oracle"]["expected_result"] = "Different behavior"
    elif fault == "oracle_digest": assertion["oracle_digest"] = acceptance_digest("other")
    elif fault == "oracle_step": assertion["source_step_index"] = 63
    elif fault == "action_index": assertion["action_index"] = 255
    elif fault == "boolean_action_index": assertion["action_index"] = True
    elif fault == "non_assertion_binding": assertion["action_index"] = 0
    elif fault == "unbound_assertion": script["actions"].append(deepcopy(script["actions"][-1]))
    elif fault == "script_code": script["actions"][0]["action"] = "evaluate"
    elif fault == "action_operand": script["actions"][0]["code"] = "process.env"
    elif fault == "empty_selector": script["actions"][0]["selector"] = " "
    elif fault in {"absolute_url", "network_path", "url_backslash"}:
        script["actions"][0] = {"action": "goto", "source_step_indices": [0],
            "url": {"absolute_url": "https://unapproved.invalid", "network_path": "//unapproved.invalid", "url_backslash": "/\\unapproved.invalid"}[fault]}
    elif fault == "gap_duplicate": output["gaps"].append({"case_id": script["case_id"], "case_digest": script["case_digest"], "description": "Unknown"})
    elif fault == "gap_digest":
        output["scripts"].pop(0)
        output["gaps"].append({"case_id": script["case_id"], "case_digest": acceptance_digest("other"), "description": "Unknown"})
    elif fault == "authority": output["execution_authorized"] = True
    else: output["passed_count"] = 7
    with pytest.raises(ValueError):
        validate_script_output(prepared, json.dumps(output))


def test_explicit_case_gaps_do_not_become_automation_coverage():
    prepared = compile_automation_input(*automation_inputs())
    output = script_output(prepared)
    script = output["scripts"].pop(0)
    output["gaps"].append({"case_id": script["case_id"], "case_digest": script["case_digest"], "description": "No independently verified DOM locator"})
    proposal = validate_script_proposal(prepared, output)
    assert proposal["gap_count"] == 1 and proposal["script_count"] + 1 == proposal["case_count"]
    assert proposal["automated_count"] == 0


def test_model_json_rejects_duplicate_keys_non_json_constants_and_unbounded_content():
    prepared = compile_automation_input(*automation_inputs())
    for content in ('{"scripts": [], "scripts": []}', '{"scripts": NaN}', "[[]]", "x" * (1024 * 1024 + 1)):
        with pytest.raises(ValueError):
            validate_script_output(prepared, content)


@pytest.mark.parametrize("action,operands", [
    ("assert_status", {"value": "400"}), ("assert_json", {"pointer": "", "value_json": '{"error":"invalid"}'}),
    ("assert_json", {"pointer": "/a~1b/~0", "value_json": "false"}),
    ("assert_header", {"name": "Content-Type", "value": "application/json"}),
])
def test_http_drafts_pin_response_assertions_without_implying_oracle_equivalence(action, operands):
    prepared = compile_automation_input(*automation_inputs())
    output = script_output(prepared, kind="http")
    target = output["scripts"][0]["actions"][-1]
    target.update(action=action)
    target.pop("value")
    target.update(operands)
    proposal = validate_script_output(prepared, json.dumps(output))
    assert proposal["status"] == "draft" and proposal["execution_authorized"] is False
    assert proposal["automated_count"] == proposal["passed_count"] == 0


@pytest.mark.parametrize("fault", ["kind", "mixed", "forward_request", "duplicate_request", "method", "url", "fragment",
    "credentials", "host", "duplicate_json", "non_json", "header_newline", "status", "pointer", "pointer_escape", "value_json"])
def test_http_dsl_rejects_unbound_targets_credentials_and_ambiguous_operands(fault):
    prepared = compile_automation_input(*automation_inputs())
    output = script_output(prepared, kind="http")
    script = output["scripts"][0]
    request, assertion = script["actions"][0], script["actions"][-1]
    if fault == "kind": script["kind"] = "arbitrary_shell"
    elif fault == "mixed": request.update(action="click", selector="#unapproved")
    elif fault == "forward_request": assertion["request_id"] = "not_yet_requested"
    elif fault == "duplicate_request": script["actions"].insert(0, deepcopy(request))
    elif fault == "method": request["method"] = "CONNECT"
    elif fault == "url": request["path"] = "https://unapproved.invalid"
    elif fault == "fragment": request["path"] = "/path#not_an_http_path"
    elif fault == "credentials": request["headers_json"] = '{"Authorization":"Bearer unsafe"}'
    elif fault == "host": request["headers_json"] = '{"Host":"unapproved.invalid"}'
    elif fault == "duplicate_json": request["body_json"] = '{"x":1,"x":2}'
    elif fault == "non_json": request["body_json"] = "NaN"
    elif fault == "header_newline": request["headers_json"] = json.dumps({"Accept": "application/json\r\nHost: unsafe"})
    elif fault == "status": assertion.update(action="assert_status", value="700")
    elif fault in {"pointer", "pointer_escape", "value_json"}:
        assertion.update(action="assert_json", pointer="a" if fault == "pointer" else "/a~2b" if fault == "pointer_escape" else "/a",
            value_json="Infinity" if fault == "value_json" else "true")
        assertion.pop("value")
    with pytest.raises(ValueError):
        validate_script_output(prepared, json.dumps(output))


def script_executor():
    _, _, deps, _ = generation_executor()
    prepared = compile_automation_input(*automation_inputs())
    class Artifacts:
        def __init__(self): self.bodies = {}
        def put(self, project, value):
            digest = acceptance_digest(value)
            self.bodies[digest] = deepcopy(value)
            return "private-specimen:" + digest, digest
        def read(self, project, ref, digest): return deepcopy(self.bodies[digest])
    class Repository:
        def __init__(self): self.stored = None; self.fail_result = False; self.calls = []
        def get(self, *args): return deepcopy(self.stored)
        def reserve(self, request, payload, *, require_current):
            require_current()
            if self.stored: raise GenerationOutcomeUnknown("already reserved")
            self.stored = {"reservation": deepcopy(payload), "reply": None, "result": None}
        def record_reply(self, request, payload, ref, digest, call, *, require_current):
            require_current()
            self.calls.append(call)
            self.stored["reply"] = {"artifact_ref": ref, "artifact_hash": digest,
                "response_hash": call.response_hash, "usage": deepcopy(payload["usage"])}
        def record_failure(self, request, ident, call): self.calls.append(call)
        def record_result(self, request, payload, ref, digest, *, require_current):
            require_current()
            if self.fail_result: raise RuntimeError("injected script result transaction failure")
            metadata = {**{key: payload[key] for key in ("script_revision_id", "project_id", "invocation_id", "call_id", "response_hash", "status")},
                "artifact_hash": digest, "input_digest": request.input_digest, "script_count": payload["proposal"]["script_count"],
                "gap_count": payload["proposal"]["gap_count"], "mapping_revision_id": request.mapping_revision_id,
                "mapping_artifact_hash": request.mapping_artifact_hash, "execution_authorized": False}
            self.stored["result"] = metadata
            self.result_value = {"metadata": metadata, "artifact_ref": ref}
            return metadata
        def result(self, *args): return deepcopy(self.result_value)
    class Provider:
        calls = 0
        error = None
        usage_source = "provider"
        async def generate(self, system, content, model, **kwargs):
            self.calls += 1
            assert json.loads(content) == prepared
            if self.error: raise self.error
            return NativeGenerationReply(json.dumps(script_output(prepared)), 123, 45, self.usage_source)
    deps["profiles"] = SimpleNamespace(resolve=lambda *args, **kwargs: deps["model"])
    from apps.api.tests.test_semantic_link_model import resolved
    from apps.api.tests.test_generation_executor import policy
    deps["model"] = resolved()
    deps["policies"] = SimpleNamespace(resolve=lambda binding: SimpleNamespace(policy=policy(binding), count=lambda *args: 32000))
    deps.update(inputs=SimpleNamespace(prepare=lambda selection: deepcopy(prepared), replay=lambda selection: deepcopy(prepared)),
        sources=SimpleNamespace(automation_bindings=lambda value: ("source",)), provider=Provider(), repository=Repository(),
        replies=Artifacts(), results=Artifacts())
    from apps.api.app.domain.quality_loop.case_approval import case_approval_basis, case_approval_cohort
    basis = case_approval_basis(prepared)
    admission = {"revision": {"revision_id": "explicit-case-admission", "artifact_hash": acceptance_digest("explicit-admission-specimen"),
        "status": "approved", "project_id": prepared["project_id"], "generation_id": prepared["generation_pin"]["generation_id"],
        "mapping_revision_id": prepared["mapping_pin"]["revision_id"], "input_digest": prepared["input_digest"],
        "cohort_id": case_approval_cohort(basis), "case_count": len(prepared["cases"])}, "basis": basis,
        "current_use": {"case_admission_current": True}}
    deps["admissions"] = SimpleNamespace(read=lambda *args: deepcopy(admission), resolve=lambda *args: deepcopy(admission))
    service = AutomationScriptGenerationApplicationService(**{key: deps[key] for key in (
        "inputs", "profiles", "policies", "authorization", "sources", "provider", "repository", "replies", "results", "admissions")})
    selection = ScriptExecutionSelection(project_id="p", mapping_revision_id="m", mapping_artifact_hash=prepared["mapping_pin"]["artifact_hash"],
        case_ids=tuple(prepared["selected_case_ids"]), model_config_id="model", budget=budget(),
        case_approval_revision_id=admission["revision"]["revision_id"], case_approval_artifact_hash=admission["revision"]["artifact_hash"])
    return service, selection, deps, prepared


def test_native_script_budget_preview_does_not_egress_or_persist_private_input():
    app, selection, deps, prepared = script_executor()
    value = app.preview(selection)
    assert deps["provider"].calls == 0 and deps["repository"].stored is None
    assert value["reservation"]["reserved_tokens"] == 136192
    assert value["request"]["input_digest"] == prepared["input_digest"]
    assert "HTTP 400" not in json.dumps(value) and "private-provider-key" not in json.dumps(value)
    assert not value["generation_authorized"] and not value["execution_authorized"]


def test_reply_precedes_draft_commit_and_same_invocation_never_resends_after_transaction_failure():
    app, selection, deps, _ = script_executor()
    request = ScriptExecutionRequest.model_validate(app.preview(selection)["request"])
    deps["repository"].fail_result = True
    with pytest.raises(RuntimeError, match="transaction failure"):
        asyncio.run(app.execute(request, invocation_id="command"))
    assert deps["provider"].calls == 1 and deps["repository"].stored["reply"]
    deps["repository"].fail_result = False
    metadata = asyncio.run(app.execute(request, invocation_id="command"))
    assert metadata["status"] == "draft" and deps["provider"].calls == 1
    assert asyncio.run(app.execute(request, invocation_id="command")) == metadata
    assert deps["provider"].calls == 1 and len(deps["repository"].calls) == 1


@pytest.mark.parametrize("failure", [RuntimeError("native disconnect"), asyncio.CancelledError()])
def test_unknown_script_calls_are_never_resent(failure):
    app, selection, deps, _ = script_executor()
    request = ScriptExecutionRequest.model_validate(app.preview(selection)["request"])
    deps["provider"].error = failure
    with pytest.raises(type(failure)):
        asyncio.run(app.execute(request, invocation_id="command"))
    with pytest.raises(GenerationOutcomeUnknown):
        asyncio.run(app.execute(request, invocation_id="command"))
    assert deps["provider"].calls == 1 and deps["repository"].stored["result"] is None


def test_source_revoke_or_missing_usage_cannot_save_or_resend_script():
    app, selection, deps, _ = script_executor()
    request = ScriptExecutionRequest.model_validate(app.preview(selection)["request"])
    deps["provider"].usage_source = "estimated"
    with pytest.raises(ValueError): asyncio.run(app.execute(request, invocation_id="command"))
    assert deps["repository"].stored["reply"] is None and deps["repository"].stored["result"] is None
    deps["provider"].usage_source = "provider"
    with pytest.raises(GenerationOutcomeUnknown): asyncio.run(app.execute(request, invocation_id="command"))
    assert deps["provider"].calls == 1
    deps["authorization"].revoked = True
    with pytest.raises(PermissionError): app.preview(selection)


def test_model_change_invalidates_script_confirmation_before_reservation():
    from dataclasses import replace
    from apps.api.app.application.quality_loop.generation_budget import GenerationBudgetInvalid

    app, selection, deps, _ = script_executor()
    request = ScriptExecutionRequest.model_validate(app.preview(selection)["request"])
    deps["model"] = replace(deps["model"], binding=replace(deps["model"].binding, config_digest=acceptance_digest("changed")))
    with pytest.raises(GenerationBudgetInvalid, match="consent changed"):
        asyncio.run(app.execute(request, invocation_id="command"))
    assert deps["provider"].calls == 0 and deps["repository"].stored is None
