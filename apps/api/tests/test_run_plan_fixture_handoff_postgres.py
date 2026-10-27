"""Canonical v3 parents and real PG/MinIO replay; setup/target/model remain explicit protocol specimens."""
import asyncio
from copy import deepcopy
from dataclasses import asdict

import pytest

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.automation_script_inputs import ScriptExecutionSelection
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureLifecycleApplicationService, HttpFixtureScope
from apps.api.app.application.quality_loop.run_plan_case_execution import RunPlanCaseExecutionApplicationService
from apps.api.app.application.quality_loop.run_plan_inputs import RunPlanSelection
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixture_binding_input import build_fixture_input
from apps.api.app.domain.quality_loop.run_plan_fixture_captures import collect_case_fixture_captures
from apps.api.app.domain.quality_loop.run_plan_case_execution import FixtureBoundRunPlanCaseScope, restore_case_scope, execution_roster
from apps.api.app.domain.shared.native_build_source import byte_digest
from apps.api.app.infrastructure.persistence.run_plan_case_execution_models import RunPlanCaseWorkRecord as Work
from apps.api.app.infrastructure.persistence.run_plan_case_execution_repository import PostgresRunPlanCaseExecutionRepository
from apps.api.app.infrastructure.persistence.run_plan_case_preparation_repository import RunPlanCasePreparationJournal
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.runner.http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage
from apps.api.app.infrastructure.storage.run_plan_case_artifacts import RunPlanCaseArtifacts
from apps.api.tests.test_http_fixture_binding_scripts import fixture_script_output
from apps.api.tests.test_http_fixtures import Runner as SetupSpecimenRunner, manifest
from apps.api.tests.test_run_plan_fixture_handoff import NativeRunner
from apps.api.tests.test_run_plan_case_execution_postgres import new_attempt, journal_counts
from apps.api.tests.test_run_plans_api import (
    native_scripts, base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping,
    reviewed_plan_inputs, preview, submit, read,
)
from apps.api.tests.test_semantic_evaluations_api import completed


def saved_fixture_plan(v):
    v["script_transport"].output = fixture_script_output
    selected = ScriptExecutionSelection.model_validate({**v["script_selection"].model_dump(mode="json"),
        "http_protocol": "nasus.runner-http-execution.v3"})
    with actor_scope(UserProfile.model_validate(v["owner"])):
        v["script_preview"] = v["script_service"].preview(selected)
    _, _, _, selection = reviewed_plan_inputs(v)
    value = selection.model_dump(mode="json")
    value["policy_revision"] = "nasus.run-plan.v3"
    value["environment"] = {**value["environment"], "kind": "local", "base_url": "http://127.0.0.1:8080"}
    for declaration in value["fixtures"]:
        recipe = {**manifest(), **{key: declaration[key] for key in ("case_id", "preconditions_digest", "setup", "cleanup")}}
        declaration["data_manifest_hash"] = acceptance_digest(recipe)
    response = preview(v, RunPlanSelection.model_validate(value))
    assert response.status_code == 200, response.text
    saved = completed(submit(v, response.json()["request"]))
    response = read(v, saved["result"]["object_refs"][0].split(":", 1)[1])
    assert response.status_code == 200, response.text
    assert response.json()["artifact"]["schema"] == "nasus.run-plan-artifact.v3"
    return {"v": v, "archive": response.json()}


def bound_attempt(parent):
    value = new_attempt(parent)
    plan, base, proofs, wires = value["plan"], value["scope"], [], []
    source_runner, verifier = SetupSpecimenRunner(), OwnedHttpFixtureObservationVerifier()
    for selected, declaration in zip(base.selection["fixture_setups"], plan["selection"]["fixtures"]):
        recipe = {**manifest(), **{key: declaration[key] for key in ("case_id", "preconditions_digest", "setup", "cleanup")}}
        scope = HttpFixtureScope(base.project_id, base.run_id, selected["case_id"], base.plan_digest,
            acceptance_digest(recipe), base.environment_id, base.target_artifact_hash, base.inventory_hash, 10000)
        command = HttpFixtureLifecycleApplicationService._command(scope, "setup", tuple(recipe["setup_steps"]))
        wire = source_runner.execute_owned_http(command, environment_id=base.environment_id,
            artifact_hash=base.target_artifact_hash, inventory_hash=base.inventory_hash, require_work=lambda: None)
        proofs.append({"invocation_id": selected["invocation_id"], "history_digest": acceptance_digest(["setup protocol specimen", selected]),
            "scope": asdict(scope), "parent": {key: getattr(base, key) for key in
                ("project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest")},
            "native_environment": {"record_id": base.selection["environment_record_id"],
                "artifact_hash": base.selection["environment_record_artifact_hash"], "inventory_hash": base.inventory_hash,
                "operator_policy_digest": acceptance_digest("explicit native policy specimen")},
            "manifest": recipe, "receipt": verifier.verify(command, wire, environment_id=base.environment_id, inventory_hash=base.inventory_hash),
            "setup_request_hash": byte_digest(wire.request_body), "setup_result_hash": byte_digest(wire.result_body)})
        wires.append(wire)
    captures = collect_case_fixture_captures(plan, base, tuple(proofs))
    inputs = tuple(build_fixture_input(capture, wire.request_body, wire.result_body) for capture, wire in zip(captures, wires))
    pins = tuple({"case_id": capture.case_id, "capture_set_digest": capture.digest, "fixture_input_digest": acceptance_digest(item)}
        for capture, item in zip(captures, inputs))
    scope = FixtureBoundRunPlanCaseScope(**asdict(base), fixture_input_pins=pins)
    value.update(scope=scope, roster=execution_roster(plan, scope), fixture_inputs=inputs, runner=NativeRunner())
    value["service"] = RunPlanCaseExecutionApplicationService(value["runner"], verifier, value["journal"], value["artifacts"])
    return value


def test_v3_original_work_pins_raw_archive_and_unknown_commit_survive_actual_pg_minio_replay(native_scripts, monkeypatch):
    parent = saved_fixture_plan(native_scripts)
    value = bound_attempt(parent)
    original = deepcopy(parent["archive"])
    result = asyncio.run(value["service"].execute(value["plan"], value["scope"], fixture_inputs=value["fixture_inputs"], require_current=lambda: None))
    size = len(value["roster"])
    assert result["state"]["state"] == "observed" and journal_counts(value) == (1, 1, 1, size, size, 1 + size * 2, 1 + size * 2)
    assert all(item["status"] == "failed" for item in result["observations"])
    with session_scope() as session:
        row = session.get(Work, value["scope"].work_id)
        assert row.scope["schema"] == "nasus.run-plan-case-fixture-scope.v1"
        persisted = restore_case_scope(row.scope)
        assert persisted == value["scope"] and RunPlanCasePreparationJournal._work(row)["schema"] == "nasus.run-plan-case-work.v2"
        assert "source_result_body_base64" not in str(row.scope) and "session_original" not in str(row.scope)
    fresh = RunPlanCaseExecutionApplicationService(None, OwnedHttpFixtureObservationVerifier(),
        PostgresRunPlanCaseExecutionRepository(), RunPlanCaseArtifacts(ObjectStorage()))
    assert fresh.read(value["plan"], persisted, fixture_inputs=value["fixture_inputs"], require_access=lambda: None) == result
    history = value["journal"].inspect(persisted, value["roster"], require_access=lambda: None)
    for outcome in history["outcomes"]:
        archived = value["artifacts"].read(persisted.project_id, outcome["artifact_ref"], outcome["artifact_hash"])
        assert archived["schema"] == "nasus.run-plan-case-native-archive.v2" and archived["fixture_input"]
    assert parent["archive"] == original
    unknown = bound_attempt(parent)
    original_event = unknown["journal"]._event

    def fail_outcome(session, scope, payload, event_type):
        original_event(session, scope, payload, event_type)
        session.flush()
        if event_type == "quality.run_plan.case_output_recorded":
            raise RuntimeError("explicit outcome Outbox rollback")

    monkeypatch.setattr(unknown["journal"], "_event", fail_outcome)
    with pytest.raises(RuntimeError, match="Outbox rollback"):
        asyncio.run(unknown["service"].execute(unknown["plan"], unknown["scope"],
            fixture_inputs=unknown["fixture_inputs"], require_current=lambda: None))
    assert journal_counts(unknown) == (1, 1, 1, 1, 0, 2, 2)
    result = fresh.read(unknown["plan"], unknown["scope"], fixture_inputs=unknown["fixture_inputs"], require_access=lambda: None)
    assert result["state"]["state"] == "outcome_unknown" and result["state"]["case_count"] == size
    assert len(unknown["runner"].commands) == 1 and result["state"]["passed_count"] == 0
