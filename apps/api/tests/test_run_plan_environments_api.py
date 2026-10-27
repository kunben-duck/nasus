"""Real PG ToolRuntime/ACL; saved parent and Docker metadata are explicit specimens."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.run_plan_environments import RUN_PLAN_ENVIRONMENT_QUERY_TOOL, RunPlanEnvironmentQuery
from apps.api.app.infrastructure.runner.configured_target_environments import ConfiguredOwnedTargetEnvironments, REGISTRY_SCHEMA
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.main import app
from apps.api.tests.test_owned_target_environment import Commands, spec
from apps.api.tests.test_run_plan_environments import state
from apps.api.tests.test_semantic_evaluations_api import completed, invoke
from apps.api.tests.test_source_access_api import policy
from apps.api.tests.test_source_evidence_api import evidence_api


@pytest.fixture
def configured_environment(evidence_api, state, tmp_path, monkeypatch):
    v, application = evidence_api, app.state.container.run_plan_environments
    owned = replace(state.spec, project_id=v["project_id"])
    commands = Commands(owned)
    registry = tmp_path / "operator.json"
    registry.write_text(json.dumps({"schema": REGISTRY_SCHEMA, "environments": [asdict(owned)]}))
    registry.chmod(0o600)
    monkeypatch.setenv("NASUS_TARGET_ENVIRONMENT_REGISTRY", str(registry))
    plan, binding = deepcopy(state.plan), deepcopy(state.binding)
    plan["metadata"]["project_id"] = binding["metadata"]["project_id"] = v["project_id"]
    plan["artifact"]["plan"]["selection"]["environment"]["inventory_hash"] = owned.digest
    query = RunPlanEnvironmentQuery(**{**state.query.model_dump(mode="json"), "project_id": v["project_id"]})
    commands.body = binding["metadata"]["target_artifact_hash"][7:].encode() + b"  /app/target.jar\n"
    def original(project, ident, *, kind):
        assert project == v["project_id"] and ident == ("plan" if kind == "plan" else "binding")
        application.authorization.require_binding_access(project, v["evidence"]["binding_id"])
        return deepcopy(plan if kind == "plan" else binding)
    monkeypatch.setattr(application, "plans", SimpleNamespace(read=lambda project, ident: original(project, ident, kind="plan")))
    monkeypatch.setattr(application, "bindings", SimpleNamespace(read=lambda project, ident: original(project, ident, kind="binding")))
    monkeypatch.setattr(application, "environments", ConfiguredOwnedTargetEnvironments(command=commands))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert application.inspect(query)["native_artifact_attested"] is True
    commands.calls.clear()
    return v, application, commands, registry, query


def test_canonical_environment_query_role_acl_historical_reads_and_shared_redaction(configured_environment):
    v, application, commands, registry, query = configured_environment
    command = completed(invoke(v, RUN_PLAN_ENVIRONMENT_QUERY_TOOL, query.model_dump(mode="json")))
    receipt = command["result"]["run_plan_environment"]
    assert receipt["query"] == query.model_dump(mode="json") and receipt["native_artifact_attested"] is True
    assert receipt["execution_authorized"] is receipt["durable_native_observation_verified"] is False
    assert receipt["passed_count"] == 0 and "container_id" not in str(receipt)
    before = len(commands.calls)
    registry.unlink()
    response = v["client"].get("/v1/tool-invocations/" + command["id"], headers=v["headers"])
    assert response.status_code == 200 and response.json()["result"]["run_plan_environment"] == receipt, response.text
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(command["id"], v["project_id"]) == receipt
    assert len(commands.calls) == before
    events = EventOutboxRepository().list_after(stream_kind="conversation", stream_id=command["conversation_id"],
        after_event_id=None, limit=1000)
    updates = [event for event in events if event.entity_id == command["id"]]
    assert updates and updates[-1].patch["status"] == "completed"
    for event in updates:
        public = event.payload["tool_invocation"]
        assert public["input_payload"] == {} and public["result"] is None
        assert "operator_policy_digest" not in str(event.model_dump())
        assert "target_artifact_hash" not in str(event.model_dump())
    original_result = deepcopy(command["result"])
    for key, value in (("execution_authorized", True), ("target_artifact_hash", "sha256:" + "0" * 64),
            ("operator_policy_digest", "sha256:" + "0" * 64), ("passed_count", 1)):
        damaged = deepcopy(original_result)
        damaged["run_plan_environment"][key] = value
        with session_scope() as session:
            session.get(ToolInvocationRecord, command["id"]).result_payload = damaged
        try:
            bad = v["client"].get("/v1/tool-invocations/" + command["id"], headers=v["headers"])
            assert bad.status_code == 502 and "operator_policy_digest" not in bad.text, bad.text
            batch = v["client"].get("/v1/tool-invocations", headers=v["headers"],
                params={"conversation_id": command["conversation_id"], "tool_id": RUN_PLAN_ENVIRONMENT_QUERY_TOOL})
            assert batch.status_code == 502 and "target_artifact_hash" not in batch.text, batch.text
            assert len(commands.calls) == before
        finally:
            with session_scope() as session:
                session.get(ToolInvocationRecord, command["id"]).result_payload = deepcopy(original_result)
    member = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(member, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    rejected = invoke(v, RUN_PLAN_ENVIRONMENT_QUERY_TOOL, query.model_dump(mode="json"), headers=v["member_headers"])
    assert rejected.status_code == 200 and rejected.json()["status"] == "failed", rejected.text
    assert len(commands.calls) == before
    assert v["client"].put(member, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    allowed = v["client"].get("/v1/tool-invocations/" + command["id"], headers=v["member_headers"])
    assert allowed.status_code == 200, allowed.text
    policy(v)
    denied = v["client"].get("/v1/tool-invocations/" + command["id"], headers=v["member_headers"])
    assert denied.status_code == 403 and "inventory_hash" not in denied.text, denied.text
    assert len(commands.calls) == before
    conversation = v["client"].get("/v1/conversations/" + command["conversation_id"], headers=v["member_headers"])
    assert conversation.status_code == 200, conversation.text
    public = next(value for value in conversation.json()["tool_invocations"] if value["id"] == command["id"])
    assert public["input_payload"] == {} and public["result"] is None
    assert "operator_policy_digest" not in conversation.text and "target_artifact_hash" not in conversation.text
    invalid = invoke(v, RUN_PLAN_ENVIRONMENT_QUERY_TOOL, {**query.model_dump(mode="json"), "container_id": "arbitrary"})
    assert invalid.status_code == 200 and invalid.json()["status"] == "failed", invalid.text
    assert len(commands.calls) == before


@pytest.mark.parametrize("change", ["source-access", "membership"])
def test_live_source_or_role_revocation_during_metadata_read_cannot_complete_inspection(configured_environment, change):
    v, application, commands, _, query = configured_environment
    member = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(member, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    hits = []
    def revoke(argv, **kwargs):
        value = commands(argv, **kwargs)
        if not hits:
            if change == "source-access":
                policy(v)
            else:
                assert v["client"].put(member, headers=v["headers"], json={"role": "viewer"}).status_code == 200
            hits.append(change)
        return value
    application.environments.command = revoke
    response = invoke(v, RUN_PLAN_ENVIRONMENT_QUERY_TOOL, query.model_dump(mode="json"), headers=v["member_headers"])
    assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    assert response.json()["result"]["run_plan_environment"] is None
    assert hits == [change] and len(commands.calls) == 1
    with session_scope() as session:
        fact = session.get(ToolInvocationRecord, response.json()["id"])
        assert fact.status == "failed" and fact.result_payload["run_plan_environment"] is None
    events = EventOutboxRepository().list_after(stream_kind="conversation", stream_id=response.json()["conversation_id"],
        after_event_id=None, limit=1000)
    updates = [event for event in events if event.entity_id == response.json()["id"]]
    assert updates and updates[-1].patch["status"] == "failed"
    assert all(event.patch["status"] != "completed" for event in updates)
    assert all(event.payload["tool_invocation"]["result"] is None for event in updates)
