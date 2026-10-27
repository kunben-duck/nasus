"""Goal explanations authorize their own persisted records, not other goals."""
from time import perf_counter
from uuid import uuid4

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.store import get_runtime_assembly
from apps.api.tests.test_agent_investigation_continuation import resume, start_structure
from apps.api.tests.test_source_access_api import grant_member, policy
from apps.api.tests.test_source_evidence_api import evidence_api


def test_http_explanation_scopes_real_history_and_rechecks_source_revocation(evidence_api, monkeypatch):
    v = evidence_api
    _, target = start_structure(v)
    target = resume(v, target["id"])
    assert target["pause_reason"] == "waiting_confirmation"
    response = v["client"].post("/v1/projects", headers=v["headers"], json={"name": f"Unrelated history {uuid4().hex}"})
    assert response.status_code == 200, response.text
    other_project = response.json()["id"]
    response = v["client"].post("/v1/conversations", headers=v["headers"], json={
        "space_type": "project", "space_id": other_project, "title": "Unrelated history"})
    assert response.status_code == 200, response.text
    response = v["client"].post("/v1/agent-goals", headers=v["headers"], json={
        "conversation_id": response.json()["id"], "project_id": other_project, "goal_template": "status_query",
        "title": "Inspect another project", "summary": "Unrelated query history",
        "steps": [{"id": "inspect", "title": "Read status", "phase": "acting", "status": "pending",
            "selected_tool_id": "query.system_image.status", "tool_input_payload": {"project_id": other_project}}]})
    assert response.status_code == 200, response.text
    other = response.json()
    assert other["id"] != target["id"]
    assembly = get_runtime_assembly()
    access = assembly.project_access
    original_invocation, original_audit = access.can_access_invocation, access.can_access_audit_event
    checked_invocations, checked_audits = [], []

    def invocation(item, *args, **kwargs):
        assert item.input_payload.get("agent_goal_id") == target["id"], "Unrelated goal receipt was inspected"
        checked_invocations.append(item.id)
        return original_invocation(item, *args, **kwargs)

    def audit(event, *args, **kwargs):
        assert event.agent_goal_id == target["id"], "Unrelated goal audit was inspected"
        checked_audits.append(event.id)
        return original_audit(event, *args, **kwargs)

    monkeypatch.setattr(access, "can_access_invocation", invocation)
    monkeypatch.setattr(access, "can_access_audit_event", audit)
    url = f"/v1/agent-goals/{target['id']}/explanation"
    started = perf_counter()
    response = v["client"].get(url, headers=v["headers"])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["goal_id"] == target["id"] and result["waiting_on"] == "user_confirmation"
    assert checked_invocations and checked_audits
    assert len(checked_audits) == len(result["audit_event_refs"])
    selected = {item.id for item in assembly.tool_invocations_app._state.list_invocations()
        if item.input_payload.get("agent_goal_id") == target["id"]}
    assert set(result["tool_invocation_refs"]) == {f"tool_invocation:{ident}" for ident in selected}
    print(f"Scoped HTTP goal explanation: receipts={len(selected)}, audits={len(checked_audits)}, "
          f"seconds={perf_counter() - started:.3f}")

    checked_invocations.clear()
    checked_audits.clear()
    denied = v["client"].get(url, headers=v["member_headers"])
    assert denied.status_code == 403
    assert not checked_invocations and not checked_audits
    grant_member(v)
    policy(v, (v["member"]["id"],))
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 200
    policy(v)
    denied = v["client"].get(url, headers=v["member_headers"])
    assert denied.status_code == 403
    assert "source_revision" not in denied.text and "Orders" not in denied.text
    assert v["client"].get(url, headers=v["headers"]).json() == result


def test_cancelled_image_explanation_keeps_saved_candidate_without_reopening_historical_gate(evidence_api):
    v = evidence_api
    fixed, built = start_structure(v)
    pending = resume(v, built["id"])
    assert pending["pause_reason"] == "waiting_confirmation"
    original = v["client"].get(
        f"/v1/projects/{v['project_id']}/system-image/build-plans/{fixed['plan_id']}", headers=v["headers"]).json()
    command_id = next(step["tool_invocation_id"] for step in reversed(pending["steps"])
        if step["status"] == "blocked" and step["tool_invocation_id"])
    command_url = f"/v1/tool-invocations/{command_id}"
    command = v["client"].get(command_url, headers=v["headers"]).json()
    assert command["status"] == "waiting_confirmation"

    # Restore a cancelled projection with its historical gate still retained.
    # This tests the persisted read model, not the structure-stop command itself.
    assembly = get_runtime_assembly()
    state = assembly.agent_application_ports.goal_lifecycle
    with actor_scope(UserProfile.model_validate(v["owner"])):
        goal = state.get_goal(pending["id"])
        checkpoint = assembly.agent_goal_state_machine.checkpoint(goal)
        assembly.agent_goal_state_machine.cancel_on_step(goal, checkpoint.blocked_step_index, "Tool work cancelled")
        state.persist_goal(goal)
    url = f"/v1/agent-goals/{pending['id']}/explanation"
    denied = v["client"].get(url, headers=v["member_headers"])
    assert denied.status_code == 403
    result = v["client"].get(url, headers=v["headers"])
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["status"] == "cancelled" and body["waiting_on"] == "none"
    assert "cancelled" in body["next_action"] and "saved artifacts" in body["next_action"]
    assert not any(term in body["next_action"].lower() for term in ("confirm", "approve", "resum"))
    assert f"tool_invocation:{command_id}" in body["tool_invocation_refs"]
    assert v["client"].get(command_url, headers=v["headers"]).json() == command
    assert v["client"].get(
        f"/v1/projects/{v['project_id']}/system-image/build-plans/{fixed['plan_id']}", headers=v["headers"]).json() == original
