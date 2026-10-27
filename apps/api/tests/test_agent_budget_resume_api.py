"""A real fixed image goal can release budget without confirming its next tool."""
import pytest
from sqlalchemy import func, select

from apps.api.app.infrastructure.persistence.agent_resume_models import AgentResumeConsumptionRecord
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.store import get_runtime_assembly
from apps.api.tests.test_agent_build_plan_api import READ_BUILD_PLAN_TOOL
from apps.api.tests.test_agent_investigation_continuation import acting, replace_graph
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_structure_build_api import request


def budget_paused_goal(v, monkeypatch, kind):
    replace_graph(monkeypatch, kind)
    fixed = request(v)
    tools = [(READ_BUILD_PLAN_TOOL, {"project_id": v["project_id"], "plan_id": fixed["plan_id"]}),
             ("system_image.build.structure", fixed)]
    response = v["client"].post("/v1/agent-goals", headers=v["headers"], json={
        "conversation_id": v["conversation"].json()["id"], "project_id": v["project_id"],
        "title": "Build budget-pinned image", "summary": "Read and build the fixed source plan",
        "goal_template": "system_image_build", "target_refs": [f"build_plan:{fixed['plan_id']}"], "max_steps": 1,
        "steps": [{"id": f"budget-work-{index}", "title": tool, "phase": "acting", "status": "pending",
            "selected_tool_id": tool, "tool_input_payload": payload} for index, (tool, payload) in enumerate(tools)]})
    assert response.status_code == 200, response.text
    paused = response.json()
    assert paused["status"] == "paused" and paused["pause_reason"] == "budget_exhausted", paused
    assert acting(paused)[0]["tool_invocation_id"] is None
    updated = v["client"].patch(f"/v1/agent-goals/{paused['id']}/budget", headers=v["headers"], json={"max_steps": 50})
    assert updated.status_code == 200, updated.text
    return updated.json()


def resume(v, expected):
    return v["client"].post(f"/v1/agent-goals/{expected['id']}/resume", headers=v["headers"],
        json={"expected_goal": expected})


def counts(goal):
    with session_scope() as session:
        return (session.scalar(select(func.count()).select_from(AgentResumeConsumptionRecord).where(
                    AgentResumeConsumptionRecord.goal_id == goal["id"])),
                session.scalar(select(func.count()).select_from(ToolInvocationRecord).where(
                    ToolInvocationRecord.conversation_id == goal["conversation_id"])))


@pytest.mark.parametrize("kind", ["local", "langgraph_postgres"])
def test_budget_release_uses_current_user_pin_and_replay_never_confirms_the_next_gate(evidence_api, monkeypatch, kind):
    v = evidence_api
    displayed = budget_paused_goal(v, monkeypatch, kind)
    before = counts(displayed)
    result = resume(v, displayed)
    assert result.status_code == 200, result.text
    pending = result.json()
    assert pending["id"] == displayed["id"] and pending["pause_reason"] == "waiting_confirmation"
    command_id = acting(pending)[1]["tool_invocation_id"]
    command = v["client"].get(f"/v1/tool-invocations/{command_id}", headers=v["headers"]).json()
    assert command["status"] == "waiting_confirmation" and "confirmed_by_user" not in command["input_payload"]
    assert counts(displayed) == (before[0] + 1, before[1] + 2)
    replace_graph(monkeypatch, kind)
    replay = resume(v, displayed)
    assert replay.status_code == 200 and replay.json() == pending
    assert counts(displayed) == (before[0] + 1, before[1] + 2)
    command = v["client"].get(f"/v1/tool-invocations/{command_id}", headers=v["headers"]).json()
    assert command["status"] == "waiting_confirmation" and "confirmed_by_user" not in command["input_payload"]


@pytest.mark.parametrize("kind", ["local", "langgraph_postgres"])
@pytest.mark.parametrize("change", ["budget", "interrupt", "input"])
def test_budget_release_rejects_a_race_at_the_real_conditional_write(evidence_api, monkeypatch, kind, change):
    v = evidence_api
    displayed = budget_paused_goal(v, monkeypatch, kind)
    before = counts(displayed)
    state = get_runtime_assembly().agent_application_ports.graph_state
    original = state.persist_goal_at_checkpoint
    concurrent = {}

    def changed_before_commit(prepared, checkpoint):
        current = ConversationRepository().get_agent_goal(prepared.id)
        if change == "budget":
            current.max_steps += 1
        elif change == "interrupt":
            current.pause_reason = "user_interrupt"
        else:
            next(step for step in current.steps if step.status == "blocked").tool_input_payload["concurrent"] = True
        ConversationRepository().upsert_goal(current)
        concurrent["goal"] = current.model_dump(mode="json")
        original(prepared, checkpoint)

    monkeypatch.setattr(state, "persist_goal_at_checkpoint", changed_before_commit)
    result = resume(v, displayed)
    assert result.status_code == 409 and result.json()["error"]["code"] == "agent_checkpoint_changed", result.text
    assert v["client"].get(f"/v1/agent-goals/{displayed['id']}", headers=v["headers"]).json() == concurrent["goal"]
    assert counts(displayed) == before


@pytest.mark.parametrize("kind", ["local", "langgraph_postgres"])
def test_public_budget_resume_recovers_after_commit_without_reissuing_consent(evidence_api, monkeypatch, kind):
    v = evidence_api
    displayed = budget_paused_goal(v, monkeypatch, kind)
    before = counts(displayed)
    state = get_runtime_assembly().agent_application_ports.graph_state
    original = state.persist_goal_at_checkpoint

    def crash_after_commit(prepared, checkpoint):
        original(prepared, checkpoint)
        raise RuntimeError("injected public budget resume failure after commit")

    monkeypatch.setattr(state, "persist_goal_at_checkpoint", crash_after_commit)
    with pytest.raises(RuntimeError, match="injected public budget"):
        resume(v, displayed)
    committed = v["client"].get(f"/v1/agent-goals/{displayed['id']}", headers=v["headers"]).json()
    assert committed["status"] == "running" and acting(committed)[0]["status"] == "pending"
    assert acting(committed)[0]["tool_invocation_id"] is None
    assert counts(displayed) == (before[0] + 1, before[1])
    monkeypatch.setattr(state, "persist_goal_at_checkpoint", original)
    replace_graph(monkeypatch, kind)
    recovered = resume(v, displayed)
    assert recovered.status_code == 200, recovered.text
    pending = recovered.json()
    assert pending["id"] == displayed["id"] and pending["pause_reason"] == "waiting_confirmation"
    assert counts(displayed) == (before[0] + 1, before[1] + 2)
    command = v["client"].get(f"/v1/tool-invocations/{acting(pending)[1]['tool_invocation_id']}", headers=v["headers"]).json()
    assert command["status"] == "waiting_confirmation" and "confirmed_by_user" not in command["input_payload"]
    replace_graph(monkeypatch, kind)
    assert resume(v, displayed).json() == pending
    assert counts(displayed) == (before[0] + 1, before[1] + 2)
