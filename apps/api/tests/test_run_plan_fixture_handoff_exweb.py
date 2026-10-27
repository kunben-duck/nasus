"""Actual original exweb/PG/MinIO/Temporal chain; model/business oracles are specimens."""
import asyncio
from copy import deepcopy
import os
import shutil
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from temporalio.client import Client, WorkflowFailureError
from temporalio.worker import Replayer, Worker

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.automation_script_inputs import ScriptExecutionSelection
from apps.api.app.application.quality_loop.run_plan_case_jobs import RunPlanCaseJobTarget
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.environment_observation_record import ENVIRONMENT_RECORD_TOOL
from apps.api.app.domain.quality_loop.http_fixture_command import FIXTURE_COMMAND_TOOL
from apps.api.app.domain.quality_loop.http_fixture_grant import GRANT_TOOL, NATIVE_GRANT_SCHEMA
from apps.api.app.domain.quality_loop.http_fixture_recipe import RECIPE_TOOL
from apps.api.app.domain.quality_loop.http_locator_record import LOCATOR_RECORD_TOOL
from apps.api.app.domain.quality_loop.run_plan_case_execution import CASE_EXECUTE_TOOL, restore_case_scope
from apps.api.app.infrastructure.config.agent_runtime_config import TemporalGatewayConfig
from apps.api.app.infrastructure.persistence.run_plan_case_execution_models import RunPlanCaseWorkRecord as Work
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.runner.configured_target_environments import ConfiguredOwnedTargetEnvironments
from apps.api.app.infrastructure.runner.owned_target_http import ConfiguredOwnedTargetHttpRunner
from apps.api.app.infrastructure.workflow.http_fixture_runtime import TemporalHttpFixtureRuntime, build_http_fixture_activities
from apps.api.app.infrastructure.workflow.nasus_http_fixture_workflow import NasusHttpFixtureWorkflow
from apps.api.app.infrastructure.workflow.nasus_run_plan_case_workflow import NasusRunPlanCaseWorkflow
from apps.api.app.infrastructure.workflow.run_plan_case_runtime import TemporalRunPlanCaseRuntime, build_run_plan_case_activities
from apps.api.tests.exweb_owned_deployment import OriginalExwebDeployment
from apps.api.tests.test_http_fixture_binding_scripts import fixture_script_output
from apps.api.tests.test_run_plan_builds_api import (
    base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping, native_scripts,
    prepared_binding, submit_binding, read_binding,
)
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, confirm
from scripts.exweb_http_fixture_probe import recipe as session_recipe


def exweb_script_specimen(prepared):
    output = fixture_script_output(prepared)
    for script in output["scripts"]:
        for action in script["actions"]:
            if action["action"] == "request":
                action["path"] = "/api/v1/finance/chat/sessions/{{session}}"
    return output


def confirmed(v, tool, value):
    pending = invoke(v, tool, value, key=uuid4().hex)
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    return completed(confirm(v, pending.json()))


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="explicit actual Temporal opt-in is required")
def test_fixed_exweb_public_v3_original_setup_handoff_uses_pg_minio_and_temporal(native_scripts, tmp_path, monkeypatch):
    import apps.api.app.bootstrap as bootstrap
    v, container = native_scripts, app.state.container
    assert v["real_build"] and len(v["exweb_files"]) == 126
    assert v["exweb_commit"] == "fe5827f6b76f77ef34918d8b452ee823142332dc"
    assert os.environ.get("NASUS_TEST_OBJECT_STORAGE_MODE") == "minio"
    with session_scope() as session:
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
    node = shutil.which("node")
    assert node is not None
    monkeypatch.setenv("NASUS_HTTP_FIXTURE_NODE", node)
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    monkeypatch.setattr(container.run_plan_cases.execution, "node_executable", node)
    monkeypatch.setattr(bootstrap, "get_application_container", lambda: container)
    v["script_transport"].output = exweb_script_specimen
    chosen = ScriptExecutionSelection.model_validate({**v["script_selection"].model_dump(mode="json"),
        "http_protocol": "nasus.runner-http-execution.v3"})
    with actor_scope(UserProfile.model_validate(v["owner"])):
        v["script_preview"] = v["script_service"].preview(chosen)
    deployment = OriginalExwebDeployment(tmp_path / "owned-original-v3-target")
    requests = []
    execute_owned = ConfiguredOwnedTargetHttpRunner.execute_owned_http

    def actual_request(runner, command, **kwargs):
        requests.append(deepcopy(command))
        return execute_owned(runner, command, **kwargs)

    monkeypatch.setattr(ConfiguredOwnedTargetHttpRunner, "execute_owned_http", actual_request)

    def start_original(built):
        with actor_scope(UserProfile.model_validate(v["owner"])):
            return deployment.start(built, container.native_builds)

    def original_recipe(declaration):
        return {**session_recipe(declaration["case_id"]),
            **{key: declaration[key] for key in ("case_id", "preconditions_digest", "setup", "cleanup")}}

    try:
        v = prepared_binding(v, monkeypatch, environment=start_original, fixture_recipe=original_recipe,
            policy_revision="nasus.run-plan.v3")
        monkeypatch.setenv("NASUS_TARGET_ENVIRONMENT_REGISTRY", str(deployment.registry))
        saved_binding = completed(submit_binding(v))
        binding_id = saved_binding["result"]["object_refs"][0].split(":", 1)[1]
        binding = read_binding(v, binding_id).json()
        saved = deepcopy(v["original_plan"])
        plan = saved["artifact"]["plan"]
        assert saved["artifact"]["schema"] == "nasus.run-plan-artifact.v3"
        assert plan["schema"] == "nasus.run-plan.v3"
        source_pin = plan["selection"]["target_build"]["code_sources"]
        assert len(source_pin) == len(v["code_roots"]) == 1
        assert len(plan["prepared"]["cases"]) == len(plan["selection"]["fixtures"]) == len(v["fixture_manifests"])
        query = {"project_id": v["project_id"], "run_plan_id": saved["metadata"]["run_plan_id"],
            "run_plan_artifact_hash": saved["metadata"]["artifact_hash"], "build_binding_id": binding_id,
            "build_binding_artifact_hash": binding["metadata"]["artifact_hash"]}
        adapter = container.run_plan_environments.environments
        assert isinstance(adapter, ConfiguredOwnedTargetEnvironments)
        environment = confirmed(v, ENVIRONMENT_RECORD_TOOL, query)["result"]["run_plan_environment_record"]["metadata"]
        locator = confirmed(v, LOCATOR_RECORD_TOOL, {key: query[key] for key in
            ("project_id", "run_plan_id", "run_plan_artifact_hash")})["result"]["run_plan_locator_record"]["metadata"]
        assert locator["summary"]["static_match"] == locator["summary"]["locator_count"] > 0
        assert environment["inventory_hash"] != environment["operator_policy_digest"]
        assert not requests
        consents = []
        for declaration, recipe in zip(plan["selection"]["fixtures"], v["fixture_manifests"]):
            assert declaration["data_manifest_hash"] == acceptance_digest(recipe)
            registered = confirmed(v, RECIPE_TOOL, {**{key: query[key] for key in
                ("project_id", "run_plan_id", "run_plan_artifact_hash")}, "manifest": recipe})
            metadata = registered["result"]["http_fixture_recipe"]["metadata"]
            consent = {"project_id": v["project_id"], "recipe_id": metadata["record_id"],
                "recipe_artifact_hash": metadata["artifact_hash"], "attempt_id": "actual-v3-fixture-" + uuid4().hex,
                "operation": "setup", "timeout_ms": 10000, "policy_revision": NATIVE_GRANT_SCHEMA,
                "environment_record_id": environment["record_id"], "environment_record_artifact_hash": environment["artifact_hash"]}
            consents.append((declaration["case_id"], consent))
        assert not requests
        config = TemporalGatewayConfig(address=os.environ["TEST_TEMPORAL_ADDRESS"],
            task_queue="nasus-actual-exweb-v3-" + uuid4().hex)
        fixture_runtime, case_runtime = TemporalHttpFixtureRuntime(config=config), TemporalRunPlanCaseRuntime(config=config)
        monkeypatch.setattr(container.http_fixture_jobs, "workflow", fixture_runtime)
        monkeypatch.setattr(container.run_plan_case_jobs, "workflow", case_runtime)
        actor = UserProfile.model_validate(v["owner"])

        async def verify():
            client = await asyncio.wait_for(Client.connect(config.address, namespace=config.namespace), 10)
            handles, setups, grants = [], [], []
            async with Worker(client, task_queue=fixture_runtime.task_queue, workflows=[NasusHttpFixtureWorkflow],
                    activities=build_http_fixture_activities()), Worker(client, task_queue=case_runtime.task_queue,
                    workflows=[NasusRunPlanCaseWorkflow], activities=build_run_plan_case_activities()):
                try:
                    for case_id, consent in consents:
                        # Do not spend a later fixture's bounded grant on earlier setup work.
                        grant = (await asyncio.to_thread(confirmed, v, GRANT_TOOL, consent))["result"]["http_fixture_grant"]["metadata"]
                        grants.append((case_id, consent, grant))
                        selection = {"project_id": v["project_id"], "grant_id": grant["record_id"],
                            "grant_digest": grant["grant_digest"], "operation": "setup"}
                        pending = await asyncio.to_thread(invoke, v, FIXTURE_COMMAND_TOOL, selection, key=uuid4().hex)
                        assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
                        response = await asyncio.to_thread(confirm, v, pending.json())
                        assert response.status_code == 200 and response.json()["status"] in {"running", "completed"}, response.text
                        ident = response.json()["id"]
                        handle = client.get_workflow_handle("nasus-http-fixture:" + ident)
                        handles.append((fixture_runtime, ident, handle))
                        assert await asyncio.wait_for(handle.result(), 900) == "completed"
                        setups.append({"case_id": case_id, "invocation_id": ident})
                    assert len(requests) == len(grants) == len(consents)
                    assert all(command.metadata["fixture_phase"] == "setup" for command in requests)
                    selection = {**query, "run_id": "actual-v3-business-" + uuid4().hex,
                        "plan_digest": plan["plan_digest"], "timeout_ms": 10000,
                        "environment_record_id": environment["record_id"], "environment_record_artifact_hash": environment["artifact_hash"],
                        "locator_record_id": locator["record_id"], "locator_record_artifact_hash": locator["artifact_hash"], "fixture_setups": setups}
                    key = uuid4().hex
                    pending = await asyncio.to_thread(invoke, v, CASE_EXECUTE_TOOL, selection, key=key)
                    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
                    with session_scope() as session:
                        assert session.scalar(select(func.count()).select_from(Work).where(Work.project_id == v["project_id"])) == 0
                    response = await asyncio.to_thread(confirm, v, pending.json())
                    assert response.status_code == 200 and response.json()["status"] in {"running", "completed"}, response.text
                    ident = response.json()["id"]
                    handle = client.get_workflow_handle("nasus-run-plan-cases:" + ident)
                    handles.append((case_runtime, ident, handle))
                    assert await asyncio.wait_for(handle.result(), 1800) == "completed"
                    target = RunPlanCaseJobTarget(project_id=v["project_id"], invocation_id=ident)

                    def read_original():
                        with actor_scope(actor):
                            return container.run_plan_case_jobs.read(target)

                    history = await asyncio.to_thread(read_original)
                    state = history["history"]["state"]
                    assert state["schema"] == "nasus.run-plan-case-state.v2" and state["state"] == "observed"
                    assert state["case_count"] == state["observed_case_count"] == len(plan["prepared"]["cases"])
                    assert state["passed_count"] == state["executed_on_target_count"] == 0
                    assert state["business_coverage_verified"] is False
                    assert all(item["status"] == "failed" for item in history["history"]["observations"])
                    business = requests[len(grants):]
                    assert len(business) == len(grants) and all(command.fixture_input for command in business)
                    assert all(command.fixture_input["capture_set"]["setup_invocation_id"] == setup["invocation_id"]
                        for command, setup in zip(business, setups))
                    with session_scope() as session:
                        work = session.scalar(select(Work).where(Work.project_id == v["project_id"]))
                        assert work is not None and work.scope["schema"] == "nasus.run-plan-case-fixture-scope.v1"
                        assert len(restore_case_scope(work.scope).fixture_input_pins) == len(grants)
                        assert "source_result_body_base64" not in str(work.scope)
                    replay = await asyncio.to_thread(invoke, v, CASE_EXECUTE_TOOL, selection, key=key)
                    assert replay.status_code == 200 and replay.json()["id"] == ident, replay.text
                    assert await case_runtime.start(ident) is False
                    assert len(requests) == len(grants) * 2
                    for runtime, invocation_id, original in handles:
                        await Replayer(workflows=[NasusHttpFixtureWorkflow, NasusRunPlanCaseWorkflow]).replay_workflow(await original.fetch_history())
                    for _, consent, _ in grants:
                        metadata = (await asyncio.to_thread(confirmed, v, GRANT_TOOL,
                            {**consent, "operation": "cleanup"}))["result"]["http_fixture_grant"]["metadata"]
                        pending = await asyncio.to_thread(invoke, v, FIXTURE_COMMAND_TOOL,
                            {"project_id": v["project_id"], "grant_id": metadata["record_id"],
                                "grant_digest": metadata["grant_digest"], "operation": "cleanup"}, key=uuid4().hex)
                        assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
                        response = await asyncio.to_thread(confirm, v, pending.json())
                        assert response.status_code == 200 and response.json()["status"] in {"running", "completed"}, response.text
                        cleanup_id = response.json()["id"]
                        cleanup_handle = client.get_workflow_handle("nasus-http-fixture:" + cleanup_id)
                        handles.append((fixture_runtime, cleanup_id, cleanup_handle))
                        assert await asyncio.wait_for(cleanup_handle.result(), 900) == "completed"
                    assert len(requests) == len(grants) * 3
                    assert await asyncio.to_thread(read_original) == history
                    assert v["original_plan"] == saved
                finally:
                    for runtime, invocation_id, original in handles:
                        await runtime.cancel(invocation_id)
                        try:
                            await asyncio.wait_for(original.result(), 30)
                        except WorkflowFailureError:
                            pass
        asyncio.run(verify())
    finally:
        cleanup = deployment.close()
        assert cleanup["verified"] is True and cleanup["remaining_owned_resources"] == [], cleanup
