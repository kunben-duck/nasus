"""The original structural goal continues; investigation has separate consent."""
import os

import pytest
from sqlalchemy import func, select

from apps.api.app.main import app
from apps.api.app.application.agent.graph import LangGraphAgentGraphRuntime, LocalAgentGraphRuntime
from apps.api.app.infrastructure.config.agent_runtime_config import LangGraphGatewayConfig
from apps.api.app.infrastructure.persistence.build_authorization_models import BuildWorkReservationRecord
from apps.api.app.infrastructure.persistence.db_models import AgentGoalRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.investigation_models import InvestigationRevisionRecord
from apps.api.app.infrastructure.persistence.structure_build_models import StructureBuildArtifactRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.workflow.langgraph_agent_gateway import LangGraphAgentLoopGateway
from apps.api.app.store import get_runtime_assembly
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_structure_build_api import request
from apps.api.tests.test_agent_build_plan_api import goal_request, READ_BUILD_PLAN_TOOL
from apps.api.tests.test_build_authorization_api import BUDGET
from apps.api.tests.test_investigation_api import read


def replace_graph(monkeypatch, kind):
    assembly = get_runtime_assembly()
    if kind == "langgraph_postgres":
        gateway = LangGraphAgentLoopGateway(assembly.agent_application_ports.graph_state,
            assembly.agent_goal_state_machine, assembly.agent_goal_plan_compiler,
            config=LangGraphGatewayConfig(graph_name="same-goal-investigation-continuation",
                checkpoint_backend="postgres", database_url=os.environ["NASUS_DATABASE_URL"]))
        graph = LangGraphAgentGraphRuntime(gateway)
    else:
        graph = LocalAgentGraphRuntime(assembly.agent_application_ports.graph_state,
            assembly.agent_goal_state_machine, assembly.agent_goal_plan_compiler)
    monkeypatch.setattr(assembly.agent_loop_runtime, "graph_runtime", graph)


def resume(v, goal_id, expected=None):
    expected = expected or v["client"].get(f"/v1/agent-goals/{goal_id}", headers=v["headers"]).json()
    response = v["client"].post(f"/v1/agent-goals/{goal_id}/resume", headers=v["headers"], json={"expected_goal": expected})
    assert response.status_code == 200, response.text
    return response.json()


def acting(goal):
    return [step for step in goal["steps"] if step["phase"] == "acting"]


def start_structure(v, *, authorized=False, fixed=None):
    fixed = fixed or request(v)
    tools = [(READ_BUILD_PLAN_TOOL, {"project_id": v["project_id"], "plan_id": fixed["plan_id"]})]
    if authorized:
        tools.append(("system_image.build.authorize", {**fixed, "budget": BUDGET}))
    tools.append(("system_image.build.structure", fixed))
    response = goal_request(v, fixed, tools)
    assert response.status_code == 200, response.text
    goal = response.json()
    assert goal["pause_reason"] == "waiting_confirmation"
    goal = resume(v, goal["id"])
    assert goal["pause_reason"] == "structural_candidate_review", goal
    return fixed, goal


@pytest.mark.parametrize("graph_kind", ["local", "langgraph_postgres"])
@pytest.mark.parametrize("authorized", [False, True])
def test_original_structure_goal_continues_with_separate_confirmation_and_pinned_gap_tasks(
        evidence_api, monkeypatch, graph_kind, authorized):
    v = evidence_api
    replace_graph(monkeypatch, graph_kind)
    fixed, goal = start_structure(v, authorized=authorized)
    original_steps = acting(goal)
    structural_id = original_steps[-1]["tool_invocation_id"]
    with session_scope() as session:
        artifact = session.get(StructureBuildArtifactRecord, structural_id)
        original_candidate = artifact.image_revision_id
    v["path"].unlink()
    replace_graph(monkeypatch, graph_kind)
    pending = resume(v, goal["id"])
    assert pending["id"] == goal["id"] and pending["pause_reason"] == "waiting_confirmation"
    steps = acting(pending)
    assert [step["tool_invocation_id"] for step in steps[:-1]] == [step["tool_invocation_id"] for step in original_steps]
    assert steps[-1]["selected_tool_id"] == "system_image.build.investigate"
    assert steps[-1]["tool_input_payload"]["image_revision_id"] == original_candidate
    assert steps[-1]["tool_input_payload"]["goal_id"] == goal["id"]
    assert steps[-1]["tool_input_payload"]["plan_digest"] == fixed["plan_digest"]
    investigation_id = steps[-1]["tool_invocation_id"]
    with session_scope() as session:
        command = session.get(ToolInvocationRecord, investigation_id)
        assert command.status == "waiting_confirmation" and "confirmed_by_user" not in command.input_payload
        assert session.get(BuildWorkReservationRecord, investigation_id) is None
        assert session.scalar(select(func.count()).select_from(InvestigationRevisionRecord).where(
            InvestigationRevisionRecord.goal_id == goal["id"])) == 0
        assert session.scalar(select(func.count()).select_from(AgentGoalRecord).where(
            AgentGoalRecord.conversation_id == goal["conversation_id"])) == 1
    # Reading/refreshing is not consent, even after the gateway is reconstructed.
    assert v["client"].get(f"/v1/agent-goals/{goal['id']}", headers=v["headers"]).json() == pending
    replace_graph(monkeypatch, graph_kind)
    final = resume(v, goal["id"])
    assert final["pause_reason"] == "build_completion_review" and final["id"] == goal["id"]
    final_steps = acting(final)
    investigation_step = next(step for step in final_steps if step["selected_tool_id"] == "system_image.build.investigate")
    assert investigation_step["tool_invocation_id"] == investigation_id
    command = v["client"].get(f"/v1/tool-invocations/{investigation_id}", headers=v["headers"]).json()
    saved = read(v, command["result"]["investigation"]["revision_id"]).json()
    assert saved["request"]["goal_id"] == goal["id"] and saved["request"]["image_revision_id"] == original_candidate
    followups = final_steps[len(steps):]
    assert [step["selected_tool_id"] for step in followups] == [task["tool_id"] for task in saved["review"]["work_items"]]
    assert all(step["status"] == "completed" for step in final_steps)
    assert final["model_calls_used"] == 0
    replace_graph(monkeypatch, graph_kind)
    replay = resume(v, goal["id"])
    assert replay["pause_reason"] == "build_completion_review"
    assert [step["tool_invocation_id"] for step in acting(replay)] == [step["tool_invocation_id"] for step in final_steps]
    assert read(v, saved["revision_id"]).json() == saved


@pytest.mark.parametrize("graph_kind", ["local", "langgraph_postgres"])
def test_crash_after_continuation_commit_recovers_original_goal_without_duplicate_commands(evidence_api, monkeypatch, graph_kind):
    v = evidence_api
    replace_graph(monkeypatch, graph_kind)
    _, goal = start_structure(v)
    original_id = acting(goal)[-1]["tool_invocation_id"]
    original_update = LocalAgentGraphRuntime._update_goal

    async def crash_after_write(self, value, *, patch, expected_resume=None):
        await original_update(self, value, patch=patch, expected_resume=expected_resume)
        if value.id == goal["id"] and patch.get("resume_mode") == "structural_candidate_investigation":
            raise RuntimeError("injected crash after continuation checkpoint")

    monkeypatch.setattr(LocalAgentGraphRuntime, "_update_goal", crash_after_write)
    with pytest.raises(RuntimeError, match="injected crash"):
        resume(v, goal["id"])
    monkeypatch.setattr(LocalAgentGraphRuntime, "_update_goal", original_update)
    persisted = v["client"].get(f"/v1/agent-goals/{goal['id']}", headers=v["headers"]).json()
    saved_steps = acting(persisted)
    assert saved_steps[-2]["tool_invocation_id"] == original_id and saved_steps[-2]["status"] == "completed"
    assert saved_steps[-1]["selected_tool_id"] == "system_image.build.investigate"
    assert saved_steps[-1]["tool_invocation_id"] is None
    v["path"].unlink()
    replace_graph(monkeypatch, graph_kind)
    recovered = resume(v, goal["id"], expected=goal)
    assert recovered["pause_reason"] == "waiting_confirmation"
    assert [step["id"] for step in acting(recovered)] == [step["id"] for step in saved_steps]
    final = resume(v, goal["id"])
    assert final["pause_reason"] == "build_completion_review"
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(StructureBuildArtifactRecord).where(
            StructureBuildArtifactRecord.invocation_id == original_id)) == 1
        assert session.scalar(select(func.count()).select_from(InvestigationRevisionRecord).where(
            InvestigationRevisionRecord.goal_id == goal["id"])) == 1


@pytest.mark.parametrize("change", ["receipt", "input", "artifact"])
def test_continuation_rejects_changed_original_receipt_or_artifact_before_new_command(evidence_api, monkeypatch, change):
    v = evidence_api
    _, goal = start_structure(v)
    compiler = get_runtime_assembly().agent_goal_plan_compiler.investigations
    if change == "artifact":
        monkeypatch.setattr(compiler.structures.repository, "completed", lambda *args, **kwargs: None)
    else:
        original = compiler.invocations.get_tool_invocation

        def altered(ident):
            value = original(ident).model_copy(deep=True)
            if ident == acting(goal)[-1]["tool_invocation_id"]:
                if change == "receipt":
                    value.result.object_refs = ["image_revision:foreign"]
                else:
                    value.input_payload["agent_goal_id"] = "foreign"
            return value

        monkeypatch.setattr(compiler.invocations, "get_tool_invocation", altered)
    denied = v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=v["headers"], json={"expected_goal": goal})
    assert denied.status_code == 409, denied.text
    assert denied.json()["error"]["code"] == {"receipt": "structure_review_receipt_changed",
        "input": "structure_review_receipt_changed", "artifact": "build_integrity_failed"}[change]
    persisted = v["client"].get(f"/v1/agent-goals/{goal['id']}", headers=v["headers"]).json()
    assert persisted["pause_reason"] == "structural_candidate_review"
    assert [step["tool_invocation_id"] for step in acting(persisted)] == [step["tool_invocation_id"] for step in acting(goal)]


def test_continuation_rechecks_source_permission_before_advancing_the_goal(evidence_api, monkeypatch):
    from apps.api.app.domain.system_image.source_access import SourceAccessDenied
    v = evidence_api
    _, goal = start_structure(v)
    structures = get_runtime_assembly().agent_goal_plan_compiler.investigations.structures

    def denied(*args, **kwargs):
        raise SourceAccessDenied("private source details")

    monkeypatch.setattr(structures, "read_completed", denied)
    result = v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=v["headers"], json={"expected_goal": goal})
    assert result.status_code == 403 and "private source details" not in result.text
    persisted = v["client"].get(f"/v1/agent-goals/{goal['id']}", headers=v["headers"]).json()
    assert persisted["pause_reason"] == "structural_candidate_review"
    assert [step["id"] for step in persisted["steps"]] == [step["id"] for step in goal["steps"]]
