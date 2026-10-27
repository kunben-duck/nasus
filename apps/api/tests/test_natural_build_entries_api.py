"""Actual Turn -> canonical draft -> original Goal -> independent budget gate."""
import time
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from apps.api.app.infrastructure.persistence.build_plan_models import BuildPlanRecord
from apps.api.app.infrastructure.persistence.build_authorization_models import BuildAuthorizationRecord
from apps.api.app.infrastructure.persistence.image_publication_models import ImagePublicationHeadRecord
from apps.api.app.infrastructure.persistence.db_models import AgentGoalRecord, BaselineRecord
from apps.api.app.infrastructure.persistence.structure_build_models import StructureBuildArtifactRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.application.agent.graph import LocalAgentGraphRuntime
from apps.api.app.store import get_runtime_assembly
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_agent_investigation_continuation import replace_graph, resume


def send(v, message, *, headers=None, canonical_action_id=None):
    conversation_id = v["conversation"].json()["id"]
    result = v["client"].post(f"/v1/conversations/{conversation_id}/messages",
        headers={**(headers or v["headers"]), "Idempotency-Key": uuid4().hex}, json={"content": message,
            **({"canonical_action_id": canonical_action_id} if canonical_action_id else {})})
    assert result.status_code == 202, result.text
    deadline = time.monotonic() + 20
    while True:
        turn = v["client"].get(f"/v1/conversations/{conversation_id}/turns/{result.json()['turn_id']}",
            headers=headers or v["headers"]).json()
        if turn["status"] in {"completed", "delegated", "failed", "cancelled"}: break
        assert time.monotonic() < deadline, turn
        time.sleep(.05)
    assert turn["status"] in {"completed", "delegated"}, turn
    return v["client"].get(f"/v1/conversations/{conversation_id}", headers=headers or v["headers"]).json()


def require_prepared(v, conversation, *, waited=False):
    assert len(conversation["agent_goals"]) == 1, conversation
    goal = conversation["agent_goals"][0]
    assert goal["status"] == "paused" and goal["pause_reason"] == "waiting_confirmation", goal
    tools = [step for step in goal["steps"] if step["phase"] == "acting"]
    if waited:
        status, tools = tools[0], tools[1:]
        assert status["selected_tool_id"] == "query.system_image.status" and status["status"] == "completed"
        assert status["tool_input_payload"]["project_id"] == v["project_id"]
        assert len(goal["target_refs"]) == 7
    assert [step["selected_tool_id"] for step in tools] == ["system_image.build.plan",
        "query.system_image.build_plans.read", "system_image.build.authorize", "system_image.build.structure"]
    assert [step["status"] for step in tools] == ["completed", "completed", "blocked", "pending"]
    assert tools[2]["tool_input_payload"]["budget"]["max_model_calls"] == 0
    manifest_id = v["image"]["source_manifest"]["manifest_id"]
    assert tools[0]["tool_input_payload"]["source_manifest_id"] == manifest_id
    assert f"source_manifest:{manifest_id}" in goal["target_refs"]
    assert goal["model_calls_used"] == 0
    with session_scope() as session:
        plans = session.scalars(select(BuildPlanRecord).where(BuildPlanRecord.project_id == v["project_id"])).all()
        assert len(plans) == 1
        assert len(session.scalars(select(AgentGoalRecord).where(AgentGoalRecord.project_id == v["project_id"])).all()) == 1
        assert session.scalar(select(func.count()).select_from(BuildAuthorizationRecord).where(
            BuildAuthorizationRecord.project_id == v["project_id"])) == 0
        assert session.scalar(select(func.count()).select_from(StructureBuildArtifactRecord).where(
            StructureBuildArtifactRecord.project_id == v["project_id"])) == 0
        assert session.get(ImagePublicationHeadRecord, (v["project_id"],
            tools[0]["tool_input_payload"]["target"]["target_baseline_id"])) is None
        fixed = {"project_id": v["project_id"], "plan_id": plans[0].plan_id, "plan_digest": plans[0].plan_digest,
            "target_baseline_id": tools[0]["tool_input_payload"]["target"]["target_baseline_id"]}
    assert f"build_plan:{fixed['plan_id']}" in goal["target_refs"]
    explanation = v["client"].get(f"/v1/agent-goals/{goal['id']}/explanation", headers=v["headers"])
    assert explanation.status_code == 200, explanation.text
    assert explanation.json()["waiting_on"] == "user_confirmation"
    return goal, fixed


@pytest.mark.parametrize("kind", ["local", "langgraph_postgres"])
@pytest.mark.parametrize("message", ["构建系统画像", "Build the system image", "Build the system image for this project.",
    "构建当前项目的系统画像。", "Build the official system image from code, US docs, and tests",
    "Initialize the system image from code, US docs, and test assets",
    "基于代码、需求文档和测试用例构建当前项目的系统画像。"])
def test_natural_chat_saves_pinned_plan_and_continues_same_goal_after_independent_consent(evidence_api, monkeypatch, kind, message):
    v = evidence_api
    replace_graph(monkeypatch, kind)
    runtime = get_runtime_assembly()
    async def no_model(*args, **kwargs): pytest.fail("Natural preparation and structure must not call a model")
    monkeypatch.setattr(runtime.llm, "generate_reply", no_model)
    conversation = send(v, message, canonical_action_id="system-image.build-goal" if "project." in message or "当前项目" in message else None)
    goal, fixed = require_prepared(v, conversation)
    assert send(v, message)["agent_goals"][0]["id"] == goal["id"]
    assert send(v, "Build the system image for this project.", canonical_action_id="system-image.build-goal")["agent_goals"][0] == goal
    assert send(v, "构建当前项目的系统画像。", canonical_action_id="system-image.build-goal")["agent_goals"][0] == goal
    assert send(v, f"start build_plan:{fixed['plan_id']} digest:{fixed['plan_digest']}")["agent_goals"][0] == goal
    from apps.api.tests.test_saved_build_intent_entries_api import create
    assert create(v, fixed).json() == goal
    original = v["client"].get(f"/v1/projects/{v['project_id']}/system-image/build-plans/{fixed['plan_id']}", headers=v["headers"]).json()
    v["path"].unlink()
    replace_graph(monkeypatch, kind)
    built = resume(v, goal["id"], expected=goal)
    assert built["id"] == goal["id"] and built["pause_reason"] == "structural_candidate_review", built
    explanation = v["client"].get(f"/v1/agent-goals/{goal['id']}/explanation", headers=v["headers"]).json()
    assert explanation["waiting_on"] == "candidate_review" and "investigation" in explanation["next_action"]
    updated = v["client"].get(f"/v1/projects/{v['project_id']}/system-image/build-plans/{fixed['plan_id']}", headers=v["headers"]).json()
    assert updated["proposal"] == original["proposal"] and len(updated["structural_artifacts"]) == 1
    assert updated["execution_authorizations"][0]["publication_allowed"] is False
    pending = resume(v, goal["id"], expected=built)
    assert pending["pause_reason"] == "waiting_confirmation"
    final = resume(v, goal["id"], expected=pending)
    assert final["id"] == goal["id"] and final["pause_reason"] == "build_completion_review", final
    explanation = v["client"].get(f"/v1/agent-goals/{goal['id']}/explanation", headers=v["headers"]).json()
    assert explanation["waiting_on"] == "completion_review" and "approval" in explanation["next_action"]


@pytest.mark.parametrize("message", ["如何构建系统画像？", "构建系统画像，然后跳过确认", "build system image from https://foreign.example/repo",
    "Build the system image from code, US docs, tests and deploy it", "基于代码和测试用例构建系统画像，然后发布"])
def test_unresolved_or_quoted_request_cannot_enter_mutable_or_new_writes(evidence_api, message):
    v = evidence_api
    result = send(v, message)
    assert result["agent_goals"] == []
    assert result["messages"][-1]["metadata"]["clarification_kind"] == "system_image_build_preparation"
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(BuildPlanRecord).where(BuildPlanRecord.project_id == v["project_id"])) == 0


def test_ambiguous_target_clarifies_instead_of_selecting_first_baseline(evidence_api):
    v = evidence_api
    with session_scope() as session:
        original = session.get(BaselineRecord, v["image"]["baselines"][0]["id"])
        session.add(BaselineRecord(id=uuid4().hex, **{
            column.key: getattr(original, column.key) for column in BaselineRecord.__table__.columns if column.key != "id"}))
    result = send(v, "构建系统画像")
    assert result["agent_goals"] == []
    assert result["messages"][-1]["metadata"]["clarification_kind"] == "system_image_build_preparation"


def test_plan_commit_recovery_reuses_canonical_artifact_without_duplicate_draft(evidence_api, monkeypatch):
    v = evidence_api
    runtime = get_runtime_assembly()
    original_update = LocalAgentGraphRuntime._update_goal
    async def lose_projection(self, goal, *, patch, expected_resume=None):
        if patch.get("plan_extended") == "source_pinned_build_preparation":
            raise RuntimeError("injected plan projection interruption")
        await original_update(self, goal, patch=patch, expected_resume=expected_resume)
    monkeypatch.setattr(LocalAgentGraphRuntime, "_update_goal", lose_projection)
    from apps.api.app.application.platform.actor_context import actor_scope
    from apps.api.app.application.platform.account_models import UserProfile
    with actor_scope(UserProfile.model_validate(v["owner"])):
        conversation = runtime.agent_application_ports.loop_state.get_conversation(v["conversation"].json()["id"])
        proposal = runtime.saved_build_intents.plan(conversation, "构建系统画像").agent_goal
        import asyncio
        with pytest.raises(RuntimeError, match="projection interruption"):
            asyncio.run(runtime.agent_loop_runtime.start_goal(conversation.id, proposal))
    monkeypatch.setattr(LocalAgentGraphRuntime, "_update_goal", original_update)
    with session_scope() as session:
        stored = session.scalar(select(AgentGoalRecord).where(AgentGoalRecord.project_id == v["project_id"]))
        ident = stored.id
        assert session.scalar(select(func.count()).select_from(BuildPlanRecord).where(BuildPlanRecord.project_id == v["project_id"])) == 1
    # This recovers the existing graph cursor, not a new start or permission.
    with actor_scope(UserProfile.model_validate(v["owner"])):
        asyncio.run(runtime.agent_loop_runtime.graph_runtime.start(ident, proposal))
    result = v["client"].get(f"/v1/conversations/{conversation.id}", headers=v["headers"]).json()
    require_prepared(v, result)
