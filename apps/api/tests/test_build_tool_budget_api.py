"""Exercise budget refusal through the real canonical runtime and Agent graph."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from apps.api.app.infrastructure.persistence.build_tool_budget_repository import BuildToolBudgetRepository
from apps.api.app.infrastructure.persistence.investigation_models import InvestigationRevisionRecord
from apps.api.app.infrastructure.persistence.structure_build_models import StructureBuildArtifactRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_build_plan_api import create, urls
from apps.api.tests.test_structure_build_api import request
from apps.api.tests.test_build_authorization_api import start, resume, BUDGET
from apps.api.tests.test_agent_build_plan_api import goal_request
from apps.api.tests.test_agent_investigation_continuation import start_structure, resume as resume_original
from apps.api.tests.test_build_plan_revision_api import capture_documents, body, prepare, confirm, history
from apps.api.tests.test_image_plan_phase_api import activation, prepare_phase, phases, current_goal


def limited_structure(v, limit):
    fixed = request(v)
    plan_id = create(v, budget={"max_tool_calls": limit})
    plan = v["client"].get(urls(v, plan_id)[1], headers=v["headers"]).json()
    return start_structure(v, fixed={**fixed, "plan_id": plan_id, "plan_digest": plan["plan_digest"]})


@pytest.mark.parametrize("preserve_candidate", [False, True])
def test_actual_goal_pauses_before_over_budget_dispatch_and_preserves_committed_work(evidence_api, preserve_candidate):
    v = evidence_api
    default = request(v)
    plan_id = create(v, budget={"max_tool_calls": 2})
    plan = v["client"].get(urls(v, plan_id)[1], headers=v["headers"]).json()
    fixed = {**default, "plan_id": plan_id, "plan_digest": plan["plan_digest"]}
    if preserve_candidate:
        goal = start(v, fixed)
    else:
        started = goal_request(v, fixed, [
            ("query.system_image.build_plans.read", {"project_id": v["project_id"], "plan_id": plan_id}),
            ("system_image.build.authorize", {**fixed, "budget": BUDGET}),
            ("system_image.build.structure", fixed)])
        assert started.status_code == 200, started.text
        goal = started.json()
    result = resume(v, goal)
    if preserve_candidate:
        assert result["pause_reason"] == "structural_candidate_review", result
        with session_scope() as session:
            original = session.scalars(select(StructureBuildArtifactRecord).where(
                StructureBuildArtifactRecord.plan_id == plan_id)).one()
            image_id = original.image_revision_id
        waiting = resume(v, result)
        assert waiting["pause_reason"] == "waiting_confirmation", waiting
        result = resume(v, waiting)
    assert result["status"] == "paused" and result["pause_reason"] == "build_tool_budget_review", result
    budget, consumed = BuildToolBudgetRepository().inspect(goal["id"])
    assert budget.max_tool_calls == 2 and budget.origin_kind == "saved_plan" and len(consumed) == 2
    denied_id = next(step["tool_invocation_id"] for step in result["steps"] if step["status"] == "blocked")
    denied = v["client"].get(f"/v1/tool-invocations/{denied_id}", headers=v["headers"]).json()
    assert denied["status"] == "failed" and denied["result"]["followup_reason"] == "build_tool_budget_review"
    assert denied_id not in {item["invocation_id"] for item in consumed}
    with session_scope() as session:
        artifacts = session.scalars(select(StructureBuildArtifactRecord).where(StructureBuildArtifactRecord.plan_id == plan_id)).all()
        assert len(artifacts) == int(preserve_candidate)
        if preserve_candidate:
            assert artifacts[0].image_revision_id == image_id
        assert not session.scalars(select(InvestigationRevisionRecord).where(InvestigationRevisionRecord.goal_id == goal["id"])).all()


@pytest.mark.parametrize("limit", [2, 3, 4])
def test_confirmed_manual_controls_share_original_limit_without_bypassing_or_double_charging(
        evidence_api, tmp_path, monkeypatch, limit):
    from apps.api.app.main import app

    v = evidence_api
    fixed, goal = limited_structure(v, limit)
    ledger = BuildToolBudgetRepository()
    budget, original = ledger.inspect(goal["id"])
    assert len(original) == 2 and budget.max_tool_calls == limit
    revision_calls, phase_calls = [], []
    revisions = app.state.container.build_plans.revisions
    phase_service = app.state.container.build_plans.phases
    revise, activate = revisions.revise, phase_service.activate

    def tracked_revision(*args, **kwargs):
        revision_calls.append(kwargs["invocation_id"])
        return revise(*args, **kwargs)

    def tracked_phase(*args, **kwargs):
        phase_calls.append(kwargs["invocation_id"])
        return activate(*args, **kwargs)

    monkeypatch.setattr(revisions, "revise", tracked_revision)
    monkeypatch.setattr(phase_service, "activate", tracked_phase)
    payload = body(v, fixed, goal, capture_documents(v, tmp_path))
    pending = prepare(v, payload)
    assert pending["status"] == "waiting_confirmation" and ledger.inspect(goal["id"]) == (budget, original)
    saved = confirm(v, pending)
    if limit == 2:
        assert saved["status"] == "failed" and saved["result"]["followup_reason"] == "build_tool_budget_review"
        assert not revision_calls and history(v, fixed, goal).json() == []
        assert ledger.inspect(goal["id"]) == (budget, original)
        assert current_goal(v, goal) == goal
        return
    assert saved["status"] == "completed" and revision_calls == [saved["id"]], saved
    _, revised = ledger.inspect(goal["id"])
    assert len(revised) == 3 and revised[:2] == original and revised[-1]["invocation_id"] == saved["id"]
    assert confirm(v, pending) == saved and revision_calls == [saved["id"]]
    assert ledger.inspect(goal["id"]) == (budget, revised)
    revision, = history(v, fixed, goal).json()
    pending_phase = prepare_phase(v, activation(v, fixed, goal, revision))
    assert pending_phase["status"] == "waiting_confirmation" and ledger.inspect(goal["id"]) == (budget, revised)
    completed = confirm(v, pending_phase)
    if limit == 3:
        assert completed["status"] == "failed" and completed["result"]["followup_reason"] == "build_tool_budget_review"
        assert not phase_calls and phases(v, fixed, goal).json() == []
        assert ledger.inspect(goal["id"]) == (budget, revised)
        assert current_goal(v, goal) == goal and history(v, fixed, goal).json() == [revision]
        return
    assert completed["status"] == "completed" and phase_calls == [completed["id"]], completed
    _, activated = ledger.inspect(goal["id"])
    assert len(activated) == 4 and activated[:3] == revised and activated[-1]["invocation_id"] == completed["id"]
    assert confirm(v, pending_phase) == completed and phase_calls == [completed["id"]]
    assert ledger.inspect(goal["id"]) == (budget, activated)
    prepared = current_goal(v, goal)
    assert prepared["steps"][:len(goal["steps"])] == goal["steps"]
    assert prepared["pause_reason"] == "build_plan_phase_prepared"
    # A receipt committed before worker acknowledgement remains the same work,
    # even after activation changed the original displayed goal checkpoint.
    from apps.api.app.application.platform.tool_models import ToolInvocation
    assert ledger.reserve(ToolInvocation.model_validate(completed))
    assert ledger.inspect(goal["id"]) == (budget, activated)
    denied = resume_original(v, goal["id"], expected=prepared)
    assert denied["pause_reason"] == "build_tool_budget_review", denied
    assert ledger.inspect(goal["id"]) == (budget, activated)
    assert len(phases(v, fixed, goal).json()) == 1


@pytest.mark.parametrize("changed", ["checkpoint", "root", "conversation", "actor", "expiry", "goal_alias"])
def test_manual_control_cannot_drain_an_unrelated_or_stale_goal(evidence_api, tmp_path, changed):
    from apps.api.app.application.platform.tool_models import ToolInvocation
    from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository

    v = evidence_api
    fixed, goal = start_structure(v)
    pending = prepare(v, body(v, fixed, goal, capture_documents(v, tmp_path)))
    command = ToolInvocation.model_validate(pending)
    command.status = "running"
    command.input_payload.update(confirmed_by_user=True, confirmed_at=datetime.now(timezone.utc).isoformat(),
        confirmed_actor_id=v["owner"]["id"])
    if changed == "checkpoint":
        expected = deepcopy(command.input_payload["expected_goal"])
        expected["steps"][-1]["title"] = "A different displayed checkpoint"
        command.input_payload["expected_goal"] = expected
    elif changed == "root":
        command.input_payload["root_plan_id"] = "another-root"
    elif changed == "conversation":
        command.conversation_id = None
    elif changed == "actor":
        command.input_payload["confirmed_actor_id"] = "missing-actor"
    elif changed == "expiry":
        command.input_payload["confirmed_at"] = "2000-01-01T00:00:00+00:00"
    else:
        command.input_payload["agent_goal_id"] = "another-goal"
    ConversationRepository().upsert_tool_invocation(command)
    ledger = BuildToolBudgetRepository()
    before = ledger.inspect(goal["id"])
    with pytest.raises((ValueError, BuildPlanIntegrityError)):
        ledger.reserve(command)
    assert ledger.inspect(goal["id"]) == before
    assert history(v, fixed, goal).json() == []
