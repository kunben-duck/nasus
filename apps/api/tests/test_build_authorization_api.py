import os
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from uuid import uuid4

import pytest
from sqlalchemy import select, update, delete
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.domain.system_image.build_authorization import AUTHORIZE_BUILD_TOOL, BuildExecutionAuthorization
from apps.api.app.infrastructure.persistence.build_authorization_models import BuildAuthorizationRecord, BuildWorkReservationRecord
from apps.api.app.infrastructure.persistence.db_models import AgentGoalRecord, ToolInvocationRecord, SSEEventOutboxRecord, BaselineRecord
from apps.api.app.infrastructure.persistence.structure_build_models import StructureBuildArtifactRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_agent_build_plan_api import goal_request
from apps.api.tests.test_structure_build_api import request, confirm
from apps.api.tests.test_source_access_api import policy


BUDGET = {"max_tool_calls": 1, "max_model_calls": 0, "max_active_seconds": 1200, "max_cost_microusd": 0}


def start(v, payload, budget=None):
    response = goal_request(v, payload, [(AUTHORIZE_BUILD_TOOL, {**payload, "budget": budget or BUDGET}),
                                       ("system_image.build.structure", payload)])
    assert response.status_code == 200, response.text
    goal = response.json()
    assert goal["pause_reason"] == "waiting_confirmation", goal
    return goal


def resume(v, goal):
    current = v["client"].get(f"/v1/agent-goals/{goal['id']}", headers=v["headers"]).json()
    response = v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=v["headers"], json={"expected_goal": current})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("graph_kind", ["local", "langgraph_postgres"])
def test_goal_confirms_plan_once_then_executes_reserved_fixed_work(evidence_api, monkeypatch, graph_kind):
    from apps.api.app.store import get_runtime_assembly
    v = evidence_api
    runtime = get_runtime_assembly()

    def replace_graph():
        if graph_kind == "local":
            return
        from apps.api.app.application.agent.graph import LangGraphAgentGraphRuntime
        from apps.api.app.infrastructure.workflow.langgraph_agent_gateway import LangGraphAgentLoopGateway
        from apps.api.app.infrastructure.config.agent_runtime_config import LangGraphGatewayConfig
        gateway = LangGraphAgentLoopGateway(runtime.agent_application_ports.graph_state,
            runtime.agent_goal_state_machine, runtime.agent_goal_plan_compiler,
            config=LangGraphGatewayConfig(graph_name="authorized-build-test", checkpoint_backend="postgres",
                                         database_url=os.environ["NASUS_DATABASE_URL"]))
        monkeypatch.setattr(runtime.agent_loop_runtime, "graph_runtime", LangGraphAgentGraphRuntime(gateway))

    replace_graph()
    payload = request(v)
    goal = start(v, payload)
    with session_scope() as session:
        assert session.scalar(select(BuildAuthorizationRecord).where(BuildAuthorizationRecord.goal_id == goal["id"])) is None
    old_manifest = v["image"]["source_manifest"]["manifest_id"]
    v["path"].write_text("class LaterVersion:\n    pass\n")
    v["invoke"]("system_image.sources.ingest")
    head = SourceSnapshotRepository().latest_manifest(v["project_id"])
    v["path"].unlink()
    replace_graph()
    completed = resume(v, goal)
    assert completed["status"] == "paused" and completed["pause_reason"] == "structural_candidate_review", completed
    acting = [step for step in completed["steps"] if step["phase"] == "acting"]
    assert [step["selected_tool_id"] for step in acting] == [AUTHORIZE_BUILD_TOOL, "system_image.build.structure"]
    with session_scope() as session:
        grant = session.scalar(select(BuildAuthorizationRecord).where(BuildAuthorizationRecord.goal_id == goal["id"]))
        assert grant.payload["source_manifest_id"] == old_manifest
        assert grant.payload["target_baseline_id"] == payload["target_baseline_id"]
        assert grant.payload["plan_digest"] == payload["plan_digest"] and grant.payload["budget"] == BUDGET
        assert grant.payload["publication_allowed"] is False
        work = session.get(ToolInvocationRecord, acting[1]["tool_invocation_id"])
        assert work.status == "completed" and "confirmed_by_user" not in work.input_payload
        assert session.get(BuildWorkReservationRecord, work.id).authorization_id == grant.authorization_id
        artifact_id = session.get(StructureBuildArtifactRecord, work.id).image_revision_id
        grant_id = grant.authorization_id
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == grant_id)).all()
        assert {item.event_type for item in events} == {"system_image.build.authorized", "system_image.build.work.reserved"}
        assert "Orders" not in str([item.event_payload for item in events])
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == head
    plan_response = v["client"].get(f"/v1/projects/{v['project_id']}/system-image/build-plans/{payload['plan_id']}", headers=v["headers"])
    assert plan_response.status_code == 200, plan_response.text
    consent = plan_response.json()["execution_authorizations"][0]
    assert consent["goal_id"] == goal["id"] and consent["budget"] == BUDGET
    assert consent["reserved_work_item_ids"] == ["structure"] and consent["unapproved_work_item_ids"] == ["review"]
    assert consent["publication_allowed"] is False
    continued = resume(v, goal)
    assert continued["pause_reason"] == "waiting_confirmation"
    investigation = [step for step in continued["steps"] if step["phase"] == "acting"][-1]
    assert investigation["selected_tool_id"] == "system_image.build.investigate"
    with session_scope() as session:
        pending = session.get(ToolInvocationRecord, investigation["tool_invocation_id"])
        assert pending.status == "waiting_confirmation" and "confirmed_by_user" not in pending.input_payload
        assert session.get(BuildWorkReservationRecord, pending.id) is None
        assert session.get(BuildAuthorizationRecord, grant_id).payload["budget"] == BUDGET
    with session_scope() as session:
        assert session.get(StructureBuildArtifactRecord, work.id).image_revision_id == artifact_id
    for statement in (update(BuildAuthorizationRecord).values(content_hash="changed"), delete(BuildAuthorizationRecord)):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement.where(BuildAuthorizationRecord.authorization_id == grant_id))


@pytest.mark.parametrize("budget", [{**BUDGET, "max_tool_calls": 81}, {**BUDGET, "max_model_calls": 1},
                                    {**BUDGET, "max_active_seconds": 1201}, {**BUDGET, "max_cost_microusd": 1}])
def test_confirming_does_not_grant_excess_budget_or_model_egress(evidence_api, budget):
    v = evidence_api
    goal = start(v, request(v), budget)
    result = resume(v, goal)
    assert result["status"] == "failed", result
    with session_scope() as session:
        assert session.scalar(select(BuildAuthorizationRecord).where(BuildAuthorizationRecord.goal_id == goal["id"])) is None


def test_authorization_without_real_goal_cannot_be_forged(evidence_api):
    v = evidence_api
    response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": AUTHORIZE_BUILD_TOOL, "conversation_id": v["conversation"].json()["id"],
        "input": {**request(v), "budget": BUDGET, "agent_goal_id": "forged", "confirmed_by_user": True}})
    assert response.json()["status"] == "waiting_confirmation", response.text
    assert confirm(v, response.json()["id"])["status"] == "failed"


def test_expired_consent_does_not_fall_back_to_a_new_confirmation(evidence_api, monkeypatch):
    v = evidence_api
    goal = start(v, request(v))
    original = BuildExecutionAuthorization.require_time_available
    calls = []

    def expire_after_authorization(self, now=None):
        calls.append(self.authorization_id)
        if len(calls) > 1:
            raise TimeoutError("test expired approved time")
        return original(self, now)

    monkeypatch.setattr(BuildExecutionAuthorization, "require_time_available", expire_after_authorization)
    result = resume(v, goal)
    assert result["status"] == "paused" and result["pause_reason"] == "build_execution_authorization_review", result
    assert resume(v, goal)["pause_reason"] == "build_execution_authorization_review"
    with session_scope() as session:
        grant = session.scalar(select(BuildAuthorizationRecord).where(BuildAuthorizationRecord.goal_id == goal["id"]))
        assert grant is not None
        assert not session.scalars(select(BuildWorkReservationRecord).where(BuildWorkReservationRecord.authorization_id == grant.authorization_id)).all()


def test_target_version_is_rechecked_before_reservation(evidence_api, monkeypatch):
    from apps.api.app.infrastructure.persistence.build_authorization_repository import BuildAuthorizationRepository
    v = evidence_api
    payload = request(v)
    goal = start(v, payload)
    original = BuildAuthorizationRepository.reserve

    def change_target(self, invocation_id, **kwargs):
        with session_scope() as session:
            baseline = session.get(BaselineRecord, payload["target_baseline_id"])
            baseline.source_version_id = "missing-version"
        return original(self, invocation_id, **kwargs)

    monkeypatch.setattr(BuildAuthorizationRepository, "reserve", change_target)
    result = resume(v, goal)
    assert result["status"] == "paused" and result["pause_reason"] == "build_execution_authorization_review", result
    with session_scope() as session:
        grant = session.scalar(select(BuildAuthorizationRecord).where(BuildAuthorizationRecord.goal_id == goal["id"]))
        assert not session.scalars(select(BuildWorkReservationRecord).where(
            BuildWorkReservationRecord.authorization_id == grant.authorization_id)).all()


def test_competing_invocations_cannot_consume_same_work_twice(evidence_api, monkeypatch):
    from apps.api.app.infrastructure.persistence.build_authorization_repository import BuildAuthorizationRepository
    from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError
    v = evidence_api
    goal = start(v, request(v))
    original = BuildAuthorizationRepository.reserve
    outcomes = {}

    def compete(self, invocation_id, **kwargs):
        duplicate_id = "competitor_" + uuid4().hex
        with session_scope() as session:
            invocation = session.get(ToolInvocationRecord, invocation_id)
            values = {column.name: getattr(invocation, column.name) for column in ToolInvocationRecord.__table__.columns}
            values.update(id=duplicate_id, idempotency_key=None, idempotency_scope=None, idempotency_fingerprint=None)
            session.add(ToolInvocationRecord(**values))

        def attempt(ident):
            try:
                outcomes[ident] = original(self, ident, **kwargs)
            except BuildPlanIntegrityError:
                outcomes[ident] = False

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(copy_context().run, attempt, ident) for ident in (invocation_id, duplicate_id)]
            for future in futures:
                future.result(timeout=20)
        assert sum(outcomes.values()) == 1
        if not outcomes[invocation_id]:
            raise BuildPlanIntegrityError("The other canonical invocation consumed the only attempt.")
        # Same invocation can recover its reservation without spending twice.
        assert original(self, invocation_id, **kwargs)
        return True

    monkeypatch.setattr(BuildAuthorizationRepository, "reserve", compete)
    result = resume(v, goal)
    assert result["status"] == "paused" and len(outcomes) == 2, result
    with session_scope() as session:
        grant = session.scalar(select(BuildAuthorizationRecord).where(BuildAuthorizationRecord.goal_id == goal["id"]))
        reservations = session.scalars(select(BuildWorkReservationRecord).where(
            BuildWorkReservationRecord.authorization_id == grant.authorization_id)).all()
        assert len(reservations) == 1 and outcomes[reservations[0].invocation_id]
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as other:
                other.execute(delete(BuildWorkReservationRecord).where(BuildWorkReservationRecord.invocation_id == reservations[0].invocation_id))


def test_source_revocation_rolls_back_reservation_and_prevents_execution(evidence_api, monkeypatch):
    from apps.api.app.infrastructure.persistence.build_authorization_repository import BuildAuthorizationRepository
    v = evidence_api
    membership = v["client"].put(f"/v1/projects/{v['project_id']}/members/{v['member']['id']}",
        headers=v["headers"], json={"role": "qa_lead"})
    assert membership.status_code == 200, membership.text
    policy(v, (v["member"]["id"],))
    member = {**v, "headers": v["member_headers"]}
    goal = start(member, request(member))
    original = BuildAuthorizationRepository.reserve

    def revoke(self, invocation_id, **kwargs):
        policy(v)
        return original(self, invocation_id, **kwargs)

    monkeypatch.setattr(BuildAuthorizationRepository, "reserve", revoke)
    result = resume(member, goal)
    assert result["status"] == "paused" and result["pause_reason"] == "build_execution_authorization_review", result
    with session_scope() as session:
        grant = session.scalar(select(BuildAuthorizationRecord).where(BuildAuthorizationRecord.goal_id == goal["id"]))
        assert grant is not None
        assert not session.scalars(select(BuildWorkReservationRecord).where(
            BuildWorkReservationRecord.authorization_id == grant.authorization_id)).all()
    assert "Orders" not in str(result)


def test_reserved_work_does_not_retain_a_revoked_write_role(evidence_api, monkeypatch):
    from apps.api.app.infrastructure.persistence.build_authorization_repository import BuildAuthorizationRepository
    v = evidence_api
    membership_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership_url, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    member = {**v, "headers": v["member_headers"]}
    goal = start(member, request(member))
    original = BuildAuthorizationRepository.reserve

    def revoke_role(self, invocation_id, **kwargs):
        reserved = original(self, invocation_id, **kwargs)
        response = v["client"].put(membership_url, headers=v["headers"], json={"role": "viewer"})
        assert response.status_code == 200, response.text
        return reserved

    monkeypatch.setattr(BuildAuthorizationRepository, "reserve", revoke_role)
    result = resume(member, goal)
    assert result["status"] == "failed", result
    work_id = next(step["tool_invocation_id"] for step in result["steps"] if step.get("selected_tool_id") == "system_image.build.structure")
    with session_scope() as session:
        assert session.get(BuildWorkReservationRecord, work_id) is not None
        assert session.get(StructureBuildArtifactRecord, work_id) is None
