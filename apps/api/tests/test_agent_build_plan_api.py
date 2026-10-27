import json
import os

import pytest
from sqlalchemy import select

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.system_image.build_plan_queries import READ_BUILD_PLAN_TOOL
from apps.api.app.domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.structure_build_models import StructureBuildArtifactRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import grant_member, policy
from apps.api.tests.test_structure_build_api import request as structure_input


def read(v, payload, *, headers=None, key=None):
    return v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json={
        "tool_id": READ_BUILD_PLAN_TOOL, "conversation_id": v["conversation"].json()["id"],
        "input": {"project_id": v["project_id"], "plan_id": payload["plan_id"]}, "idempotency_key": key,
        "initiator_surface": "agent_loop", "initiator_actor": "agent"})


def test_real_plan_receipt_replay_and_agent_projection(evidence_api):
    v = evidence_api
    payload = structure_input(v)
    response = read(v, payload, key="pinned-plan-read")
    assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    item = response.json()
    receipt = item["result"]["build_plan_query"]
    assert receipt["plan_digest"] == payload["plan_digest"]
    assert receipt["source_manifest_id"] == v["image"]["source_manifest"]["manifest_id"]
    assert read(v, payload, key="pinned-plan-read").json()["id"] == item["id"]
    with session_scope() as session:
        record = session.get(ToolInvocationRecord, item["id"])
        assert record.result_payload["build_plan_query"] == receipt
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == item["id"])).all()
        assert events
        stored = json.dumps(record.result_payload) + json.dumps([event.event_payload for event in events])
    for secret in ("private Orders", "class Orders", "orders.py", "s3://", "local-object://"):
        assert secret not in response.text + stored
    with actor_scope(UserProfile.model_validate(v["owner"])):
        observation = app.state.container.tool_evidence.describe(item["id"], v["project_id"])
    assert observation["work_items"][0]["proposed_tool_id"] == "system_image.build.structure"
    assert observation["sources"][0]["source_revision_id"] == v["revision"]
    v["path"].write_text("class LaterVersion:\n    pass\n")
    v["invoke"]("system_image.sources.ingest")
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(item["id"], v["project_id"]) == observation


def test_plan_query_and_agent_replay_reauthorize_sources(evidence_api):
    v = evidence_api
    payload = structure_input(v)
    grant_member(v)
    policy(v, (v["member"]["id"],))
    response = read(v, payload, headers=v["member_headers"])
    assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    item = response.json()
    policy(v)
    denied = read(v, payload, headers=v["member_headers"])
    assert denied.json()["status"] == "failed" and "private Orders" not in denied.text
    with actor_scope(UserProfile.model_validate(v["member"])):
        with pytest.raises((SourceAccessDenied, StaleSourceAccessScope)):
            app.state.container.tool_evidence.describe(item["id"], v["project_id"])


def goal_request(v, payload, tools):
    return v["client"].post("/v1/agent-goals", headers=v["headers"], json={
        "conversation_id": v["conversation"].json()["id"], "project_id": v["project_id"],
        "title": "Build fixed system image", "summary": "Investigate the pinned plan",
        "goal_template": "system_image_build", "target_refs": [f"build_plan:{payload['plan_id']}"],
        "steps": [{"id": f"work-{index}", "title": tool, "phase": "acting", "status": "pending",
            "selected_tool_id": tool, "tool_input_payload": body} for index, (tool, body) in enumerate(tools)]})


@pytest.mark.parametrize("graph_kind", ["local", "langgraph_postgres"])
def test_actual_agent_goal_reads_plan_confirms_fixed_work_and_retains_review_gate(evidence_api, monkeypatch, graph_kind):
    v = evidence_api
    def replace_graph():
        if graph_kind == "local":
            return
        from apps.api.app.store import get_runtime_assembly
        from apps.api.app.application.agent.graph import LangGraphAgentGraphRuntime
        from apps.api.app.infrastructure.workflow.langgraph_agent_gateway import LangGraphAgentLoopGateway
        from apps.api.app.infrastructure.config.agent_runtime_config import LangGraphGatewayConfig
        runtime = get_runtime_assembly()
        gateway = LangGraphAgentLoopGateway(runtime.agent_application_ports.graph_state,
            runtime.agent_goal_state_machine, runtime.agent_goal_plan_compiler,
            config=LangGraphGatewayConfig(graph_name="fixed-plan-test", checkpoint_backend="postgres",
                                          database_url=os.environ["NASUS_DATABASE_URL"]))
        monkeypatch.setattr(runtime.agent_loop_runtime, "graph_runtime", LangGraphAgentGraphRuntime(gateway))

    replace_graph()
    payload = structure_input(v)
    response = goal_request(v, payload, [(READ_BUILD_PLAN_TOOL, {"project_id": v["project_id"], "plan_id": payload["plan_id"]}),
                                       ("system_image.build.structure", payload)])
    assert response.status_code == 200, response.text
    goal = response.json()
    assert goal["status"] == "paused" and goal["pause_reason"] == "waiting_confirmation", goal
    acting = [step for step in goal["steps"] if step["phase"] == "acting"]
    assert [step["selected_tool_id"] for step in acting] == [READ_BUILD_PLAN_TOOL, "system_image.build.structure"]
    assert acting[0]["status"] == "completed"
    with actor_scope(UserProfile.model_validate(v["owner"])):
        observed = app.state.container.tool_evidence.describe(acting[0]["tool_invocation_id"], v["project_id"])
    assert observed["plan_digest"] == payload["plan_digest"]
    v["path"].write_text("class Replacement:\n    pass\n")
    v["invoke"]("system_image.sources.ingest")
    head = SourceSnapshotRepository().latest_manifest(v["project_id"])
    v["path"].unlink()
    from apps.api.app.application.system_image.service import SystemImageService
    monkeypatch.setattr(SystemImageService, "ingest_sources", lambda *a, **kw: pytest.fail("Agent recaptured mutable inputs"))
    replace_graph()  # Reconstruct the graph gateway; the cursor must survive in PostgreSQL.
    resumed = v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=v["headers"], json={"expected_goal": goal})
    assert resumed.status_code == 200, resumed.text
    result = resumed.json()
    assert result["status"] == "paused" and result["pause_reason"] == "structural_candidate_review", result
    with session_scope() as session:
        artifact = session.get(StructureBuildArtifactRecord, acting[1]["tool_invocation_id"])
        assert artifact is not None and artifact.plan_digest == payload["plan_digest"]
        revision_id = artifact.image_revision_id
    revision = v["client"].get(f"/v1/projects/{v['project_id']}/system-image/revisions/{revision_id}", headers=v["headers"])
    assert revision.status_code == 200, revision.text
    assert revision.json()["revision"]["manifest_id"] == observed["source_manifest_id"]
    assert revision.json()["revision"]["status"] == "candidate"
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == head
    retry = v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=v["headers"], json={"expected_goal": result})
    assert retry.json()["pause_reason"] == "waiting_confirmation"
    continued = [step for step in retry.json()["steps"] if step["phase"] == "acting"]
    assert [step["selected_tool_id"] for step in continued] == [READ_BUILD_PLAN_TOOL, "system_image.build.structure", "system_image.build.investigate"]
    assert continued[1]["tool_invocation_id"] == acting[1]["tool_invocation_id"]
    assert continued[2]["tool_input_payload"]["image_revision_id"] == revision_id
    assert continued[2]["tool_input_payload"]["goal_id"] == goal["id"]
    with session_scope() as session:
        assert session.get(StructureBuildArtifactRecord, acting[1]["tool_invocation_id"]).image_revision_id == revision_id
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(acting[0]["tool_invocation_id"], v["project_id"]) == observed


def test_manual_pinned_goal_rejects_mutable_fallback_with_safe_error(evidence_api):
    v = evidence_api
    payload = structure_input(v)
    response = goal_request(v, payload, [("system_image.context.materialize", {"project_id": v["project_id"]})])
    assert response.status_code == 400 and "pinned_image_mutation" in response.text, response.text
