"""User-visible preconditions and durable replay must not authorize the next gate."""
import pytest
from sqlalchemy import func, select

from apps.api.app.infrastructure.persistence.agent_resume_models import AgentResumeConsumptionRecord
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.investigation_models import InvestigationRevisionRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.store import get_runtime_assembly
from apps.api.tests.agent_chat_helpers import post_chat_turn
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_agent_investigation_continuation import acting, replace_graph, start_structure


def post(v, goal, *, headers=None):
    return v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=headers or v["headers"],
        json={"expected_goal": goal})


@pytest.mark.parametrize("graph_kind", ["local", "langgraph_postgres"])
def test_old_user_snapshot_replays_without_confirming_a_later_investigation(evidence_api, monkeypatch, graph_kind):
    v = evidence_api
    replace_graph(monkeypatch, graph_kind)
    _, displayed = start_structure(v)
    result = post(v, displayed)
    assert result.status_code == 200, result.text
    pending = result.json()
    assert pending["pause_reason"] == "waiting_confirmation"
    command_id = acting(pending)[-1]["tool_invocation_id"]
    replace_graph(monkeypatch, graph_kind)
    assert post(v, displayed).json() == pending
    command = v["client"].get(f"/v1/tool-invocations/{command_id}", headers=v["headers"]).json()
    assert command["status"] == "waiting_confirmation" and "confirmed_by_user" not in command["input_payload"]
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(AgentResumeConsumptionRecord).where(
            AgentResumeConsumptionRecord.goal_id == displayed["id"])) == 1
    assert post(v, displayed, headers=v["member_headers"]).status_code == 403
    final = post(v, pending)
    assert final.status_code == 200 and final.json()["pause_reason"] == "build_completion_review"
    replace_graph(monkeypatch, graph_kind)
    assert post(v, displayed).json() == final.json()


@pytest.mark.parametrize("change", ["budget", "input", "workflow", "interrupt"])
def test_user_snapshot_change_is_rejected_before_compilation_or_tool_confirmation(evidence_api, monkeypatch, change):
    v = evidence_api
    _, displayed = start_structure(v)
    current = ConversationRepository().get_agent_goal(displayed["id"])
    if change == "budget":
        current.max_steps += 1
    elif change == "input":
        next(step for step in current.steps if step.status == "blocked").tool_input_payload["control"] = "changed"
    elif change == "workflow":
        current.workflow_id = "different_workflow"
    else:
        current.pause_reason = "user_interrupt"
    ConversationRepository().upsert_goal(current)
    before = current.model_dump(mode="json")
    response = post(v, displayed)
    assert response.status_code == 409 and response.json()["error"]["code"] == "agent_checkpoint_changed"
    assert ConversationRepository().get_agent_goal(current.id).model_dump(mode="json") == before
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(AgentResumeConsumptionRecord).where(
            AgentResumeConsumptionRecord.goal_id == current.id)) == 0
        assert session.scalar(select(func.count()).select_from(ToolInvocationRecord).where(
            ToolInvocationRecord.conversation_id == current.conversation_id,
            ToolInvocationRecord.tool_id == "system_image.build.investigate")) == 0


def test_fixed_image_http_resume_requires_the_displayed_precondition_and_exact_schema(evidence_api):
    v = evidence_api
    _, displayed = start_structure(v)
    url = f"/v1/agent-goals/{displayed['id']}/resume"
    assert v["client"].post(url, headers=v["headers"]).status_code == 428
    changed = {**displayed, "unexpected_checkpoint_field": True}
    response = post(v, changed)
    assert response.status_code == 409 and response.json()["error"]["code"] == "agent_checkpoint_invalid"
    assert v["client"].get(f"/v1/agent-goals/{displayed['id']}", headers=v["headers"]).json() == displayed


@pytest.mark.parametrize("graph_kind", ["local", "langgraph_postgres"])
def test_chat_can_confirm_the_exact_fixed_investigation_without_bypassing_resume_pins(evidence_api, monkeypatch, graph_kind):
    v = evidence_api
    replace_graph(monkeypatch, graph_kind)
    _, displayed = start_structure(v)
    pending = post(v, displayed).json()
    command_id = acting(pending)[-1]["tool_invocation_id"]
    assert pending["pause_reason"] == "waiting_confirmation"
    path = f"/v1/conversations/{pending['conversation_id']}/messages"
    content = {"content": f"确认 {command_id}"}
    assert v["client"].post(path, headers=v["member_headers"], json=content).status_code == 403
    replace_graph(monkeypatch, graph_kind)
    turn = post_chat_turn(v, pending["conversation_id"], content["content"])
    assert turn["status"] == "completed", turn
    final = v["client"].get(f"/v1/agent-goals/{pending['id']}", headers=v["headers"]).json()
    assert final["id"] == displayed["id"] and final["pause_reason"] == "build_completion_review"
    assert turn["result"]["agent_goal"]["id"] == final["id"]
    assert turn["result"]["tool_invocation"]["id"] == command_id
    command = v["client"].get(f"/v1/tool-invocations/{command_id}", headers=v["headers"]).json()
    assert command["status"] == "completed"
    assert post(v, displayed).json() == final


@pytest.mark.parametrize("graph_kind", ["local", "langgraph_postgres"])
def test_chat_budget_race_fails_without_confirming_or_replacing_the_command(evidence_api, monkeypatch, graph_kind):
    v = evidence_api
    replace_graph(monkeypatch, graph_kind)
    _, displayed = start_structure(v)
    pending = post(v, displayed).json()
    command_id = acting(pending)[-1]["tool_invocation_id"]
    service = get_runtime_assembly().agent_service
    original = service.resume_goal
    captured = []

    async def changed_before_driver(goal_id, *, expected_resume):
        captured.append(expected_resume)
        expected_resume.require_matches(pending)
        current = ConversationRepository().get_agent_goal(goal_id)
        current.max_steps += 1
        ConversationRepository().upsert_goal(current)
        return await original(goal_id, expected_resume=expected_resume)

    monkeypatch.setattr(service, "resume_goal", changed_before_driver)
    turn = post_chat_turn(v, pending["conversation_id"], f"确认 {command_id}")
    assert turn["status"] == "failed", turn
    assert len(captured) == 1
    current = v["client"].get(f"/v1/agent-goals/{pending['id']}", headers=v["headers"]).json()
    assert current == {**pending, "max_steps": pending["max_steps"] + 1}
    command = v["client"].get(f"/v1/tool-invocations/{command_id}", headers=v["headers"]).json()
    assert command["status"] == "waiting_confirmation" and "confirmed_by_user" not in command["input_payload"]
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(InvestigationRevisionRecord).where(
            InvestigationRevisionRecord.goal_id == pending["id"])) == 0
