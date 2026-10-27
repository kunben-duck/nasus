"""A concurrent change between preparation and commit must stop continuation."""
import pytest
from sqlalchemy import func, select

from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.store import get_runtime_assembly
from apps.api.tests.test_agent_investigation_continuation import replace_graph, start_structure, acting
from apps.api.tests.test_source_evidence_api import evidence_api


@pytest.mark.parametrize("graph_kind", ["local", "langgraph_postgres"])
@pytest.mark.parametrize("change", ["budget", "input", "invocation", "interrupt"])
def test_prepared_structure_continuation_cannot_overwrite_a_concurrent_checkpoint(
        evidence_api, monkeypatch, graph_kind, change):
    v = evidence_api
    replace_graph(monkeypatch, graph_kind)
    _, goal = start_structure(v)
    compiler = get_runtime_assembly().agent_goal_plan_compiler
    original = compiler.compile_structure_continuation
    changed = {}
    with session_scope() as session:
        count = session.scalar(select(func.count()).select_from(ToolInvocationRecord).where(
            ToolInvocationRecord.conversation_id == goal["conversation_id"]))

    def change_after_preparation(preparing):
        continuation = original(preparing)
        persisted = ConversationRepository().get_agent_goal(preparing.id)
        if change == "budget":
            persisted.max_steps += 1
        elif change == "input":
            next(step for step in persisted.steps if step.status == "blocked").tool_input_payload["new_control"] = "changed"
        elif change == "invocation":
            next(step for step in persisted.steps if step.status == "blocked").tool_invocation_id = "inv_concurrent"
        else:
            persisted.pause_reason = "user_interrupt"
        ConversationRepository().upsert_goal(persisted)
        changed["goal"] = persisted.model_dump(mode="json")
        return continuation

    monkeypatch.setattr(compiler, "compile_structure_continuation", change_after_preparation)
    response = v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=v["headers"], json={"expected_goal": goal})
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "agent_checkpoint_changed"
    persisted = v["client"].get(f"/v1/agent-goals/{goal['id']}", headers=v["headers"]).json()
    assert persisted == changed["goal"]
    assert len(acting(persisted)) == len(acting(goal))
    assert all(step["selected_tool_id"] != "system_image.build.investigate" for step in acting(persisted))
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(ToolInvocationRecord).where(
            ToolInvocationRecord.conversation_id == goal["conversation_id"])) == count
