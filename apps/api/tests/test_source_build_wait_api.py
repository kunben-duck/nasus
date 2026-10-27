"""Real persisted missing-code goals continue without granting structural consent."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from apps.api.app.infrastructure.persistence.agent_resume_models import AgentResumeConsumptionRecord
from apps.api.app.infrastructure.persistence.build_plan_models import BuildPlanRecord
from apps.api.app.infrastructure.persistence.build_authorization_models import BuildAuthorizationRecord
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.db_models import AgentGoalRecord, ToolInvocationRecord
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.store import get_runtime_assembly
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_natural_build_entries_api import send
from apps.api.tests.test_agent_investigation_continuation import replace_graph, resume
from apps.api.tests.test_targeted_build_intent_api import changed_version
from apps.api.tests.test_build_plan_api import urls


def fresh_project(v):
    project = v["client"].post("/v1/projects", headers=v["headers"], json={"name": f"Waiting {uuid4().hex}"})
    assert project.status_code == 200, project.text
    project_id = project.json()["id"]
    conversation = v["client"].post("/v1/conversations", headers=v["headers"], json={
        "space_type": "project", "space_id": project_id, "title": "Wait for captured inputs"})
    assert conversation.status_code == 200, conversation.text
    return {**v, "project_id": project_id, "conversation": conversation}


def count(record, project_id):
    with session_scope() as session:
        return session.scalar(select(func.count()).select_from(record).where(record.project_id == project_id))


def capture_code(v, path):
    for tool, input_payload in (("system_image.sources.register", {"source_specs": [
            {"source_type": "code", "source_uri": str(path)}]}), ("system_image.sources.ingest", {})):
        captured = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
            "conversation_id": v["conversation"].json()["id"], "tool_id": tool,
            "input": {"project_id": v["project_id"], **input_payload}})
        assert captured.status_code == 200 and captured.json()["status"] == "completed", captured.text


def start_waiting(v, monkeypatch, kind):
    replace_graph(monkeypatch, kind)
    runtime = get_runtime_assembly()
    async def no_model(*args, **kwargs):
        pytest.fail("A missing-code intent and structural draft do not authorize model calls")
    monkeypatch.setattr(runtime.llm, "generate_reply", no_model)
    conversation = send(v, "Build the system image for this project.", canonical_action_id="system-image.build-goal")
    assert len(conversation["agent_goals"]) == 1
    goal = conversation["agent_goals"][0]
    assert goal["status"] == "paused" and goal["pause_reason"] == "missing_captured_code", goal
    assert goal["model_calls_used"] == 0
    return goal


def resume_response(v, goal):
    return v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=v["headers"],
        json={"expected_goal": goal})


def require_no_preparation(v, goal):
    assert ConversationRepository().get_agent_goal(goal["id"]).model_dump(mode="json") == goal
    assert count(BuildPlanRecord, v["project_id"]) == count(BuildAuthorizationRecord, v["project_id"]) == 0
    assert count(AgentResumeConsumptionRecord, v["project_id"]) == 0
    assert count(AgentGoalRecord, v["project_id"]) == 1


@pytest.mark.parametrize("kind", ["local", "langgraph_postgres"])
@pytest.mark.parametrize("message", ["Build the official system image from code, US docs, and tests",
    "基于代码、需求文档和测试用例构建当前项目的系统画像。"])
def test_source_category_request_waits_for_code_and_reuses_the_same_goal_after_capture(evidence_api, monkeypatch, kind, message):
    v = fresh_project(evidence_api)
    replace_graph(monkeypatch, kind)
    async def no_model(*args, **kwargs):
        pytest.fail("Describing source categories grants no model authorization")
    monkeypatch.setattr(get_runtime_assembly().llm, "generate_reply", no_model)
    conversation = send(v, message)
    assert len(conversation["agent_goals"]) == 1
    waiting = conversation["agent_goals"][0]
    assert waiting["pause_reason"] == "missing_captured_code"
    require_no_preparation(v, waiting)
    capture_code(v, v["path"])
    image = v["client"].get(f"/v1/projects/{v['project_id']}/system-image", headers=v["headers"])
    assert image.status_code == 200, image.text
    v["image"] = image.json()
    from apps.api.tests.test_natural_build_entries_api import require_prepared
    prepared, _ = require_prepared(v, send(v, message), waited=True)
    assert prepared["id"] == waiting["id"] and prepared["workflow_id"] == waiting["workflow_id"]
    assert prepared["model_calls_used"] == 0 and prepared["active_started_at"] is None
    assert count(BuildAuthorizationRecord, v["project_id"]) == 0


@pytest.mark.parametrize("kind", ["local", "langgraph_postgres"])
def test_long_human_wait_and_budget_gate_do_not_exhaust_or_reset_active_runtime(evidence_api, monkeypatch, kind):
    v = fresh_project(evidence_api)
    waiting = start_waiting(v, monkeypatch, kind)
    goal = ConversationRepository().get_agent_goal(waiting["id"])
    assert goal.active_runtime_ms is not None and goal.active_started_at is None
    # Simulate an old paused goal without sleeping or resetting spent work.
    goal.started_at = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    goal.active_runtime_ms = max(goal.active_runtime_ms, 250)
    goal.max_runtime_seconds = 60
    ConversationRepository().upsert_goal(goal)
    waiting = goal.model_dump(mode="json")
    capture_code(v, v["path"])
    replace_graph(monkeypatch, kind)
    pending = resume(v, waiting["id"], expected=waiting)
    assert pending["pause_reason"] == "waiting_confirmation", pending
    assert pending["started_at"] == waiting["started_at"]
    assert pending["active_started_at"] is None and waiting["active_runtime_ms"] <= pending["active_runtime_ms"] < 60000
    spent = pending["active_runtime_ms"]
    assert resume(v, waiting["id"], expected=waiting) == pending
    v["path"].unlink()
    built = resume(v, waiting["id"], expected=pending)
    assert built["pause_reason"] == "structural_candidate_review", built
    assert built["active_started_at"] is None and spent <= built["active_runtime_ms"] < 60000
    assert built["started_at"] == waiting["started_at"]


@pytest.mark.parametrize("kind", ["local", "langgraph_postgres"])
def test_resume_of_a_spent_runtime_stays_paused_until_explicit_budget_increase(evidence_api, monkeypatch, kind):
    v = fresh_project(evidence_api)
    waiting = start_waiting(v, monkeypatch, kind)
    goal = ConversationRepository().get_agent_goal(waiting["id"])
    goal.active_runtime_ms = 65000
    goal.max_runtime_seconds = 60
    ConversationRepository().upsert_goal(goal)
    waiting = goal.model_dump(mode="json")
    capture_code(v, v["path"])
    paused = resume(v, waiting["id"], expected=waiting)
    assert paused["pause_reason"] == "budget_exhausted" and paused["budget_exhausted_reason"] == "max_runtime_seconds", paused
    assert paused["active_runtime_ms"] >= 65000 and paused["active_started_at"] is None
    assert count(BuildPlanRecord, v["project_id"]) == count(BuildAuthorizationRecord, v["project_id"]) == 0
    changed = v["client"].patch(f"/v1/agent-goals/{waiting['id']}/budget", headers=v["headers"], json={"max_runtime_seconds": 120})
    assert changed.status_code == 200, changed.text
    assert changed.json()["active_runtime_ms"] == paused["active_runtime_ms"]
    pending = resume(v, waiting["id"], expected=changed.json())
    assert pending["pause_reason"] == "waiting_confirmation" and pending["active_runtime_ms"] >= 65000, pending
    assert count(BuildPlanRecord, v["project_id"]) == 1 and count(BuildAuthorizationRecord, v["project_id"]) == 0


@pytest.mark.parametrize("kind", ["local", "langgraph_postgres"])
@pytest.mark.parametrize("channel", ["explicit_resume", "guided_message"])
def test_capture_resumes_original_waiting_goal_and_stale_pin_does_not_confirm_budget(evidence_api, monkeypatch, kind, channel):
    v = fresh_project(evidence_api)
    waiting = start_waiting(v, monkeypatch, kind)
    original = next(step for step in waiting["steps"] if step["phase"] == "acting")
    assert original["selected_tool_id"] == "query.system_image.status" and original["status"] == "blocked"
    assert len(waiting["target_refs"]) == 3 and waiting["model_calls_used"] == 0
    assert count(BuildPlanRecord, v["project_id"]) == count(BuildAuthorizationRecord, v["project_id"]) == 0
    assert send(v, "构建系统画像")["agent_goals"][0] == waiting
    assert resume(v, waiting["id"], expected=waiting) == waiting
    assert count(AgentResumeConsumptionRecord, v["project_id"]) == 0

    capture_code(v, v["path"])
    replace_graph(monkeypatch, kind)
    if channel == "explicit_resume":
        prepared = resume(v, waiting["id"], expected=waiting)
    else:
        prepared = send(v, "Build the system image for this project.",
            canonical_action_id="system-image.build-goal")["agent_goals"][0]
    assert prepared["id"] == waiting["id"] and prepared["workflow_id"] == waiting["workflow_id"]
    assert prepared["pause_reason"] == "waiting_confirmation", prepared
    tools = [step for step in prepared["steps"] if step["phase"] == "acting"]
    assert [step["selected_tool_id"] for step in tools] == ["query.system_image.status", "system_image.build.plan",
        "query.system_image.build_plans.read", "system_image.build.authorize", "system_image.build.structure"]
    assert [step["status"] for step in tools] == ["completed", "completed", "completed", "blocked", "pending"]
    assert tools[0]["tool_input_payload"] == original["tool_input_payload"]
    assert tools[0]["tool_invocation_id"] == original["tool_invocation_id"]
    assert tools[1]["tool_input_payload"]["target"] == original["tool_input_payload"]["build_input_request"]["target"]
    assert len(prepared["target_refs"]) == 7 and waiting["target_refs"][-1] in prepared["target_refs"]
    assert count(AgentGoalRecord, v["project_id"]) == count(BuildPlanRecord, v["project_id"]) == 1
    assert count(BuildAuthorizationRecord, v["project_id"]) == 0
    assert count(AgentResumeConsumptionRecord, v["project_id"]) == 1
    assert resume(v, waiting["id"], expected=waiting) == prepared
    assert count(BuildAuthorizationRecord, v["project_id"]) == 0
    assert send(v, "构建系统画像")["agent_goals"][0] == prepared
    v["path"].unlink()
    built = resume(v, waiting["id"], expected=prepared)
    assert built["id"] == waiting["id"] and built["pause_reason"] == "structural_candidate_review", built
    assert count(BuildAuthorizationRecord, v["project_id"]) == 1


@pytest.mark.parametrize("kind", ["local", "langgraph_postgres"])
def test_target_drift_while_waiting_does_not_consume_or_replace_the_original_intent(evidence_api, monkeypatch, kind):
    v = fresh_project(evidence_api)
    waiting = start_waiting(v, monkeypatch, kind)
    capture_code(v, v["path"])
    request = next(step for step in waiting["steps"] if step["phase"] == "acting")["tool_input_payload"]["build_input_request"]
    changed_version(v, request["target"]["target_baseline_id"])
    rejected = resume_response(v, waiting)
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error"]["code"] == "build_preparation_scope_changed"
    require_no_preparation(v, waiting)
    assert "source_uri" not in rejected.text and str(v["path"]) not in rejected.text


@pytest.mark.parametrize("kind", ["local", "langgraph_postgres"])
def test_membership_revocation_while_waiting_prevents_resume_without_changing_history(evidence_api, monkeypatch, kind):
    v = fresh_project(evidence_api)
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    conversation = v["client"].post("/v1/conversations", headers=v["member_headers"], json={
        "space_type": "project", "space_id": v["project_id"], "title": "Waiting member"})
    assert conversation.status_code == 200, conversation.text
    member_view = {**v, "headers": v["member_headers"], "conversation": conversation}
    waiting = start_waiting(member_view, monkeypatch, kind)
    capture_code(v, v["path"])
    assert v["client"].delete(membership, headers=v["headers"]).status_code == 200
    rejected = resume_response(member_view, waiting)
    assert rejected.status_code == 403, rejected.text
    require_no_preparation(v, waiting)
    assert str(v["path"]) not in rejected.text


@pytest.mark.parametrize("kind", ["local", "langgraph_postgres"])
def test_newly_captured_source_restriction_is_checked_before_resume(evidence_api, monkeypatch, kind):
    v = fresh_project(evidence_api)
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    conversation = v["client"].post("/v1/conversations", headers=v["member_headers"], json={
        "space_type": "project", "space_id": v["project_id"], "title": "Source-scoped waiting"})
    assert conversation.status_code == 200, conversation.text
    member_view = {**v, "headers": v["member_headers"], "conversation": conversation}
    waiting = start_waiting(member_view, monkeypatch, kind)
    capture_code(v, v["path"])
    policies = SourceAccessRepository()
    snapshot = policies.load_snapshot(v["project_id"])
    assert len(snapshot.bindings) == 1
    policies.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted", ()),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="fixture-" + uuid4().hex)
    rejected = resume_response(member_view, waiting)
    assert rejected.status_code == 403, rejected.text
    require_no_preparation(v, waiting)
    assert str(v["path"]) not in rejected.text


@pytest.mark.parametrize("kind", ["local", "langgraph_postgres"])
@pytest.mark.parametrize("change", ["canonical-input", "result-scope"])
def test_original_status_receipt_is_rechecked_from_pg_before_fixing_inputs(evidence_api, monkeypatch, kind, change):
    v = fresh_project(evidence_api)
    waiting = start_waiting(v, monkeypatch, kind)
    capture_code(v, v["path"])
    original = next(step for step in waiting["steps"] if step["phase"] == "acting")
    field = "input_payload" if change == "canonical-input" else "result_payload"
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, original["tool_invocation_id"])
        before = deepcopy(getattr(row, field))
        if change == "canonical-input":
            row.input_payload = {**before, "build_input_request": {**before["build_input_request"], "objective": "Different intent"}}
        else:
            row.result_payload = {**before, "object_refs": ["project:foreign"]}
    try:
        rejected = resume_response(v, waiting)
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["error"]["code"] == "build_input_wait_scope_changed"
        require_no_preparation(v, waiting)
    finally:
        with session_scope() as session:
            setattr(session.get(ToolInvocationRecord, original["tool_invocation_id"]), field, before)


@pytest.mark.parametrize("kind", ["local", "langgraph_postgres"])
def test_concurrent_input_resumes_have_one_commit_and_cannot_release_the_budget(evidence_api, monkeypatch, kind):
    v = fresh_project(evidence_api)
    waiting = start_waiting(v, monkeypatch, kind)
    capture_code(v, v["path"])
    compiler = get_runtime_assembly().agent_goal_plan_compiler
    original = compiler.compile_source_input_continuation
    barrier = Barrier(2)

    def prepared_together(goal):
        continuation = original(goal)
        barrier.wait(timeout=20)
        return continuation

    monkeypatch.setattr(compiler, "compile_source_input_continuation", prepared_together)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: resume_response(v, waiting), range(2)))
    monkeypatch.setattr(compiler, "compile_source_input_continuation", original)
    assert sorted(response.status_code for response in responses) == [200, 409], [response.text for response in responses]
    assert next(response for response in responses if response.status_code == 409).json()["error"]["code"] == "agent_checkpoint_changed"
    winner = next(response.json() for response in responses if response.status_code == 200)
    assert winner["id"] == waiting["id"] and winner["workflow_id"] == waiting["workflow_id"]
    assert winner["pause_reason"] == "waiting_confirmation" and winner["model_calls_used"] == 0
    assert count(AgentResumeConsumptionRecord, v["project_id"]) == count(BuildPlanRecord, v["project_id"]) == 1
    assert count(BuildAuthorizationRecord, v["project_id"]) == 0
    assert count(AgentGoalRecord, v["project_id"]) == 1
    replay = resume_response(v, waiting)
    assert replay.status_code == 200 and replay.json() == winner, replay.text
    assert count(BuildAuthorizationRecord, v["project_id"]) == 0


@pytest.mark.parametrize("kind", ["local", "langgraph_postgres"])
@pytest.mark.parametrize("change", ["budget", "interrupt"])
def test_prepared_inputs_cannot_overwrite_a_concurrent_goal_checkpoint(evidence_api, monkeypatch, kind, change):
    v = fresh_project(evidence_api)
    waiting = start_waiting(v, monkeypatch, kind)
    capture_code(v, v["path"])
    compiler = get_runtime_assembly().agent_goal_plan_compiler
    original = compiler.compile_source_input_continuation
    changed = {}

    def change_after_preparation(goal):
        continuation = original(goal)
        persisted = ConversationRepository().get_agent_goal(goal.id)
        if change == "budget":
            persisted.max_steps += 1
        else:
            persisted.pause_reason = "user_interrupt"
        ConversationRepository().upsert_goal(persisted)
        changed["goal"] = persisted.model_dump(mode="json")
        return continuation

    monkeypatch.setattr(compiler, "compile_source_input_continuation", change_after_preparation)
    rejected = resume_response(v, waiting)
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error"]["code"] == "agent_checkpoint_changed"
    require_no_preparation(v, changed["goal"])


@pytest.mark.parametrize("kind", ["local", "langgraph_postgres"])
@pytest.mark.parametrize("inputs", ["failed-code", "failed-optionals", "only-optionals"])
def test_required_code_and_optional_failures_have_distinct_recovery_semantics(evidence_api, monkeypatch, kind, inputs):
    v = fresh_project(evidence_api)
    waiting = start_waiting(v, monkeypatch, kind)
    missing = v["path"].parent / "not-present-for-ingestion.md"
    assert not missing.exists()
    if inputs == "failed-code":
        sources = [{"source_type": "code", "source_uri": str(missing)}]
    elif inputs == "failed-optionals":
        sources = [{"source_type": "code", "source_uri": str(v["path"])},
            {"source_type": "us_doc", "source_uri": str(missing)},
            {"source_type": "test_asset", "source_uri": str(missing)}]
    else:
        sources = [{"source_type": "us_doc", "source_uri": str(v["path"])}]
    registered = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "conversation_id": v["conversation"].json()["id"], "tool_id": "system_image.sources.register",
        "input": {"project_id": v["project_id"], "source_specs": sources}})
    assert registered.status_code == 200 and registered.json()["status"] == "completed", registered.text
    ingested = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "conversation_id": v["conversation"].json()["id"], "tool_id": "system_image.sources.ingest",
        "input": {"project_id": v["project_id"]}})
    assert ingested.status_code == 200, ingested.text
    continued = resume_response(v, waiting)
    assert continued.status_code == 200, continued.text
    if inputs != "failed-optionals":
        assert ingested.json()["status"] == "failed", ingested.text
        assert continued.json() == waiting
        require_no_preparation(v, waiting)
        return

    assert ingested.json()["status"] == "completed", ingested.text
    prepared = continued.json()
    assert prepared["id"] == waiting["id"] and prepared["pause_reason"] == "waiting_confirmation"
    assert prepared["model_calls_used"] == 0 and count(BuildAuthorizationRecord, v["project_id"]) == 0
    plan_id = next(ref.split(":", 1)[1] for ref in prepared["target_refs"] if ref.startswith("build_plan:"))
    saved = v["client"].get(urls(v, plan_id)[1], headers=v["headers"])
    assert saved.status_code == 200, saved.text
    plan = saved.json()
    assert sorted((member["source_type"], member["status"]) for member in plan["proposal"]["intent"]["sources"]) == [
        ("code", "captured"), ("test_asset", "failed"), ("us_doc", "failed")]
    gaps = {gap["code"] for gap in plan["proposal"]["gaps"]}
    assert {"us_doc_unavailable", "test_asset_unavailable"}.issubset(gaps)
    assert "captured_code_required" not in gaps
    v["path"].unlink()
    built = resume(v, waiting["id"], expected=prepared)
    assert built["id"] == waiting["id"] and built["pause_reason"] == "structural_candidate_review", built
    assert built["model_calls_used"] == 0 and count(BuildAuthorizationRecord, v["project_id"]) == 1
    assert resume_response(v, waiting).json() == built
