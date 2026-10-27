"""Full original handoff/Node worker contracts; target, model and journals are explicit specimens."""
import asyncio
from copy import deepcopy
from dataclasses import asdict, replace
import json
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.run_plan_case_execution import RunPlanCaseExecutionApplicationService
from apps.api.app.application.quality_loop.run_plan_case_inputs import PreparedFixtureBoundCaseInputs
from apps.api.app.application.quality_loop.run_plan_cases import RunPlanCaseApplicationService
from apps.api.app.application.quality_loop.runner_port import FixtureBoundHttpCommand, OwnedTargetHttpExecution
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan import compile_run_plan
from apps.api.app.domain.quality_loop.run_plan_case_execution import (
    FixtureBoundRunPlanCaseScope, RunPlanCaseExecutionInvalid, restore_case_scope, execution_roster, case_work_schema,
)
from apps.api.app.domain.shared.native_build_source import byte_digest
from apps.api.app.infrastructure.runner.adapters import HttpAutomationRunner
from apps.api.app.infrastructure.runner.http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from apps.api.app.infrastructure.runner.request_wire import runner_request_body
from apps.api.tests.test_http_fixture_binding_input import probe
from apps.api.tests.test_http_fixture_binding_scripts import fixture_plan_inputs
from apps.api.tests.test_http_fixtures import manifest
from apps.api.tests.test_run_plan_case_execution import Journal, Artifacts
from apps.api.tests.test_run_plan_case_inputs import case_inputs, spec


def fixture_saved_inputs():
    draft, review, sources, selection = fixture_plan_inputs()
    selection["environment"]["base_url"] = "http://127.0.0.1:8080"
    for declaration in selection["fixtures"]:
        recipe = {**manifest(), **{key: declaration[key] for key in ("case_id", "preconditions_digest", "setup", "cleanup")}}
        declaration["data_manifest_hash"] = acceptance_digest(recipe)
    plan = compile_run_plan(draft, review, selection, sources)
    first = selection["fixtures"][0]
    recipe = {**manifest(), **{key: first[key] for key in ("case_id", "preconditions_digest", "setup", "cleanup")}}
    archive = {"project_id": plan["project_id"], "run_plan_id": "new-fixture-plan", "plan": plan}
    metadata = dict(project_id=plan["project_id"], run_plan_id="new-fixture-plan", artifact_hash=acceptance_digest(archive),
        plan_digest=plan["plan_digest"], **{key: sources[key] for key in ("image_revision_id", "manifest_id")})
    return None, None, recipe, {"metadata": metadata, "artifact": archive}


@pytest.fixture
def fixture_inputs(spec, monkeypatch):
    from apps.api.tests import test_run_plan_case_inputs as module
    original_inventory = module.inventory_for

    def inventory(plan, **kwargs):
        return original_inventory(plan, java='import org.springframework.web.bind.annotation.*;\n'
            '@RestController class Controller { @GetMapping("/sessions/{id}") String read() { return "ok"; } }')

    monkeypatch.setattr(module, "http_saved_inputs", fixture_saved_inputs)
    monkeypatch.setattr(module, "inventory_for", inventory)
    return case_inputs.__wrapped__(spec, monkeypatch)


class NativeRunner:
    def __init__(self):
        self.commands, self.visits, self.fail = [], [], False

    def execute_owned_http(self, command, *, environment_id, artifact_hash, inventory_hash, require_work):
        require_work()
        self.commands.append(deepcopy(command))
        if self.fail:
            raise ConnectionError("explicit lost native response specimen")
        wire = runner_request_body(command)
        native = probe(wire)
        assert native["accepted"] is True
        self.visits.extend(native["visits"])
        result = HttpAutomationRunner._result_from_payload(command, native["result"], request_hash=byte_digest(wire))
        require_work()
        return OwnedTargetHttpExecution(result, wire, json.dumps(native["result"]).encode(), environment_id, inventory_hash)


def composed(v):
    runner, journal, artifacts = NativeRunner(), Journal(), Artifacts()
    worker = RunPlanCaseExecutionApplicationService(runner, OwnedHttpFixtureObservationVerifier(), journal, artifacts)
    return SimpleNamespace(service=RunPlanCaseApplicationService(v.service, worker), worker=worker,
        runner=runner, journal=journal, artifacts=artifacts)


def test_full_producer_fixes_original_native_bytes_without_changing_legacy_proofs(fixture_inputs):
    v = fixture_inputs
    prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    assert type(prepared) is PreparedFixtureBoundCaseInputs and type(prepared.scope) is FixtureBoundRunPlanCaseScope
    assert len(prepared.fixture_inputs) == len(prepared.fixture_captures) == len(prepared.plan["prepared"]["cases"])
    assert restore_case_scope(json.loads(json.dumps(asdict(prepared.scope)))) == prepared.scope
    assert case_work_schema(prepared.scope) == "nasus.run-plan-case-work.v2"
    first = v.selection.fixture_setups[0]
    proof = v.fixtures.read(v.selection.project_id, first.invocation_id, require_current=lambda: None)
    wire = v.fixtures.read_native(v.selection.project_id, first.invocation_id, require_current=lambda: None)
    assert wire.proof == proof and set(proof) == {"invocation_id", "history_digest", "scope", "parent", "native_environment",
        "manifest", "receipt", "setup_request_hash", "setup_result_hash"}
    assert wire.request_body == v.state["phases"][0][1].execution.request_body
    assert "request_body=" not in repr(wire) and "result_body=" not in repr(wire)
    for capsule, value, pin in zip(prepared.fixture_captures, prepared.fixture_inputs, prepared.scope.fixture_input_pins):
        assert capsule.scope_digest == prepared.scope.base_scope.digest
        assert pin == {"case_id": capsule.case_id, "capture_set_digest": capsule.digest, "fixture_input_digest": acceptance_digest(value)}
    v.service.require_current(prepared)
    assert v.service.historical_inputs(prepared.scope).fixture_inputs == prepared.fixture_inputs
    assert len(v.runner.commands) == v.state["initial_request_count"]


def test_original_setup_resources_reach_the_full_native_worker_and_archive_replay(fixture_inputs):
    v, app = fixture_inputs, composed(fixture_inputs)
    before = deepcopy((v.v.saved, v.snapshot, v.locator, v.state["phases"]))
    history = asyncio.run(app.service.execute(v.selection, invocation_id=v.snapshot["id"]))
    assert history["state"]["schema"] == "nasus.run-plan-case-state.v2" and history["state"]["state"] == "observed"
    assert len(app.runner.commands) == history["state"]["case_count"] == len(v.selection.fixture_setups)
    assert len(app.journal.claims) == len(app.journal.outcomes) == len(app.runner.commands)
    assert all(type(command) is FixtureBoundHttpCommand for command in app.runner.commands)
    assert all(visit["method"] == "GET" and visit["path"].startswith("/sessions/") for visit in app.runner.visits)
    assert all("{{" not in visit["path"] for visit in app.runner.visits)
    for command, observed, row in zip(app.runner.commands, history["observations"], history["state"]["cases"]):
        assert observed["schema"] == "nasus.run-plan-case-observation.v2"
        assert observed["fixture_input_digest"] == acceptance_digest(command.fixture_input)
        script = next(item for item in v.v.saved["artifact"]["plan"]["proposal"]["scripts"] if item["case_id"] == command.us_id)
        assert len(observed["oracles"]) == len(script["assertions"])
        assert [item["oracle_digest"] for item in observed["oracles"]] == [item["oracle_digest"] for item in script["assertions"]]
        assert observed["status"] == row["status"] == "failed"  # ACTIVE does not satisfy the independent original oracle.
    assert all(value["schema"] == "nasus.run-plan-case-native-archive.v2" for value in app.artifacts.values.values())
    assert app.service.read(app.journal.scope) == history and len(app.runner.commands) == len(v.selection.fixture_setups)
    assert (v.v.saved, v.snapshot, v.locator, v.state["phases"]) == before
    assert history["state"]["passed_count"] == history["state"]["executed_on_target_count"] == 0
    assert history["state"]["business_coverage_verified"] is False


@pytest.mark.parametrize("fault", ["missing", "reordered", "wire", "value", "extra", "other_scope", "other_pin"])
def test_forged_or_incomplete_handoff_rejected_before_lease_claim_or_native_dispatch(fixture_inputs, fault):
    v, app = fixture_inputs, composed(fixture_inputs)
    prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    values, scope = deepcopy(prepared.fixture_inputs), prepared.scope
    if fault == "missing": values = values[:-1]
    elif fault == "reordered": values = tuple(reversed(values))
    elif fault == "wire": values[0]["source_result_body_base64"] += "\n"
    elif fault == "value": values[0]["capture_set"]["captures"][0]["value"] = "invented-resource"
    elif fault == "extra": values[0]["verified"] = True
    elif fault == "other_scope": scope = scope.base_scope
    else:
        pins = deepcopy(scope.fixture_input_pins)
        pins[0]["fixture_input_digest"] = acceptance_digest("other original wire")
        scope = replace(scope, fixture_input_pins=pins)
    with pytest.raises(ValueError):
        asyncio.run(app.worker.execute(prepared.plan, scope, fixture_inputs=values, require_current=lambda: None))
    assert app.journal.scope is None and app.journal.claims == app.journal.outcomes == []
    assert app.runner.commands == [] and app.artifacts.values == {}


def test_committed_claim_without_response_stays_unknown_and_never_redispatches(fixture_inputs):
    v, app = fixture_inputs, composed(fixture_inputs)
    app.runner.fail = True
    first = asyncio.run(app.service.execute(v.selection, invocation_id=v.snapshot["id"]))
    assert first["state"]["state"] == "outcome_unknown" and first["state"]["outcome_unknown_case_count"] == 1
    assert first["state"]["not_dispatched_case_count"] == len(v.selection.fixture_setups) - 1
    app.journal.expired = True
    app.runner.fail = False
    assert asyncio.run(app.service.execute(v.selection, invocation_id=v.snapshot["id"])) == first
    assert len(app.runner.commands) == 1 and app.journal.outcomes == []


def test_archive_rebinding_is_rejected_even_when_its_outer_hash_is_recomputed(fixture_inputs):
    app = composed(fixture_inputs)
    asyncio.run(app.service.execute(fixture_inputs.selection, invocation_id=fixture_inputs.snapshot["id"]))
    outcome = app.journal.outcomes[0]
    value = deepcopy(app.artifacts.values[outcome["artifact_hash"]])
    value["fixture_input"]["source_result_body_base64"] += "\n"
    new_hash = acceptance_digest(value)
    app.artifacts.values[new_hash] = value
    outcome.update(artifact_hash=new_hash, artifact_ref="private-case://" + new_hash)
    with pytest.raises(RunPlanCaseExecutionInvalid): app.service.read(app.journal.scope)


@pytest.mark.parametrize("fault", ["unknown_schema", "missing_pin", "extra_scope", "reorder", "boolean_digest"])
def test_new_scope_protocol_cannot_downgrade_or_drop_the_full_original_roster(fixture_inputs, fault):
    prepared = fixture_inputs.service.prepare(fixture_inputs.selection, invocation_id=fixture_inputs.snapshot["id"])
    scope = json.loads(json.dumps(asdict(prepared.scope)))
    if fault == "unknown_schema": scope["schema"] = "future-scope"
    elif fault == "missing_pin": scope["fixture_input_pins"].pop()
    elif fault == "extra_scope": scope["verified"] = True
    elif fault == "reorder": scope["fixture_input_pins"].reverse()
    else: scope["fixture_input_pins"][0]["fixture_input_digest"] = True
    with pytest.raises(RunPlanCaseExecutionInvalid): restore_case_scope(scope)
    assert len(execution_roster(prepared.plan, prepared.scope)) == len(prepared.plan["prepared"]["cases"])


def portal_specimen():
    with pytest.MonkeyPatch.context() as monkeypatch:
        v = fixture_inputs.__wrapped__(spec.__wrapped__(), monkeypatch)
        app = composed(v)
        prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
        history = asyncio.run(app.service.execute(v.selection, invocation_id=v.snapshot["id"]))
        command = {**deepcopy(v.snapshot), "status": "completed"}
        return {"plan": deepcopy(v.v.saved), "input": v.selection.model_dump(mode="json"), "command": command,
            "view": {"project_id": prepared.scope.project_id, "invocation_id": prepared.scope.invocation_id,
                "run_id": prepared.scope.run_id, "status": "completed", "bound": True, "history": history,
                "historical_not_live": True, "business_coverage_verified": False, "canonical_execution_committed": False}}


if __name__ == "__main__":
    print(json.dumps(portal_specimen()))
