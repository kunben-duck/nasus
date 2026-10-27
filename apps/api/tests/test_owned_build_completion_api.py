from copy import deepcopy
import json

import pytest
from sqlalchemy import select, update

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.infrastructure.persistence.db_models import AgentGoalRecord, SSEEventOutboxRecord, ToolInvocationRecord, UserIdentityRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_build_completion_api import completion, submit as assess, report
from apps.api.tests.test_build_gap_ownership_api import assign, ownership
from apps.api.tests.test_investigation_api import investigation
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import grant_member, policy


@pytest.fixture
def owned(completion):
    v = completion
    v["completion_input"] = {**v["completion_input"], "analyses": [], "analysis_policy": "committed_build"}
    v["assessment"] = assess(v, key="original-v2-assessment").json()
    assert v["assessment"]["status"] == "completed", v["assessment"]
    response = report(v, v["assessment"]["id"])
    assert response.status_code == 200, response.text
    v["original_report"] = response.json()
    view = ownership(v).json()
    v["assignment_input"] = {"project_id": v["project_id"], "completion_invocation_id": v["assessment"]["id"],
        "completion_report_hash": v["assessment"]["result"]["build_completion"]["report_hash"],
        "expected_goal": v["completion_input"]["expected_goal"], "parent_revision_id": None, "parent_revision_hash": None,
        "assignments": [{"gap_id": gap["gap_id"], "owner_actor_id": v["owner"]["id"],
                         "reason": "Review this unresolved gap independently"} for gap in view["gaps"]]}
    saved = assign(v, key="confirmed-owner-revision")
    assert saved.status_code == 200 and saved.json()["status"] == "completed", saved.text
    receipt = saved.json()["result"]["build_gap_ownership"]
    v["owned_input"] = {**v["completion_input"], "ownership_pin": {key: receipt[key] for key in
        ("completion_invocation_id", "completion_report_hash", "revision_id", "revision_hash")}}
    v["assignment"] = saved.json()
    return v


def test_owned_assessment_is_independent_private_and_does_not_mutate_original_or_goal(owned):
    v = owned
    response = assess(v, v["owned_input"], key="fixed-owner-completion")
    assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    command = response.json()
    observed = report(v, command["id"])
    assert observed.status_code == 200 and observed.headers["cache-control"] == "private, no-store", observed.text
    body = observed.json()
    assert body["schema"] == "nasus.image-build-completion.v3" and body["state"] == "blocked"
    assert "gap_ownership_unassigned" not in body["blockers"]
    assert {"full_plan_budget_unverified", "critical_conflicts_unverified"} <= set(body["blockers"])
    assert all(gap["resolution_status"] == "unresolved" and gap["ownership_status"] == "confirmed" for gap in body["gaps"])
    assert not any(body[key] for key in ("goal_completed", "candidate_ready", "publication_authorized", "execution_authorized"))
    assert report(v, v["assessment"]["id"]).json() == v["original_report"]
    goal = v["completion_input"]["expected_goal"]
    assert v["client"].get(f"/v1/agent-goals/{goal['id']}", headers=v["headers"]).json() == goal
    assert assess(v, v["owned_input"], key="fixed-owner-completion").json()["id"] == command["id"]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(command["id"], v["project_id"]) == body
    with session_scope() as session:
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == command["id"])).all()
    public = json.dumps(command["result"]) + json.dumps([event.event_payload for event in events])
    assert not any(value in public for value in ('"ownership_pin":', '"gaps":', '"source_scans":', '"revision_hash":', "orders.py", "s3://"))


@pytest.mark.parametrize("damage", ["report_hash", "revision_hash", "missing_revision", "different_checkpoint", "unknown_pin", "v1"])
def test_owned_assessment_rejects_unconfirmed_foreign_or_changed_proof(owned, damage):
    v = owned
    body = deepcopy(v["owned_input"])
    if damage in {"report_hash", "revision_hash"}:
        body["ownership_pin"]["completion_report_hash" if damage == "report_hash" else "revision_hash"] = "sha256:" + "0" * 64
    elif damage == "missing_revision":
        body["ownership_pin"]["revision_id"] = "not-a-saved-revision"
    elif damage == "different_checkpoint":
        body["expected_goal"]["summary"] = "changed checkpoint"
    elif damage == "unknown_pin":
        body["ownership_pin"]["latest"] = True
    else:
        old = assess(v, {key: value for key, value in v["completion_input"].items() if key != "analysis_policy"}).json()
        assert old["status"] == "completed"
        body["ownership_pin"]["completion_invocation_id"] = old["id"]
        body["ownership_pin"]["completion_report_hash"] = old["result"]["build_completion"]["report_hash"]
    result = assess(v, body)
    assert result.status_code == 403 or result.status_code == 200 and result.json()["status"] == "failed", result.text
    if result.status_code == 200:
        assert result.json()["result"].get("build_completion") is None


def test_refinement_cannot_be_used_as_another_ownership_root(owned):
    v = owned
    command = assess(v, v["owned_input"]).json()
    assert command["status"] == "completed", command
    denied = v["client"].get(f"/v1/projects/{v['project_id']}/system-image/build-completions/{command['id']}/gap-ownership", headers=v["headers"])
    assert denied.status_code == 502 and '"gaps":' not in denied.text, denied.text


def test_historical_refinement_keeps_exact_old_owners_after_reassignment_and_later_goal_changes(owned):
    v = owned
    command = assess(v, v["owned_input"]).json()
    assert command["status"] == "completed", command
    original = report(v, command["id"]).json()
    first = ownership(v).json()
    grant_member(v)
    response = assign(v, {**v["assignment_input"], "parent_revision_id": first["revision_id"],
        "parent_revision_hash": first["revision_hash"], "assignments": [{**item, "owner_actor_id": v["member"]["id"]}
            for item in v["assignment_input"]["assignments"]]})
    assert response.json()["status"] == "completed", response.text
    assert report(v, command["id"]).json() == original
    assert original["ownership"]["revision_id"] != ownership(v).json()["revision_id"]
    with session_scope() as session:
        session.execute(update(AgentGoalRecord).where(AgentGoalRecord.id == v["completion_input"]["expected_goal"]["id"]).values(summary="later checkpoint"))
    assert report(v, command["id"]).json() == original
    assert assess(v, v["owned_input"]).json()["status"] == "failed"


def test_current_owner_eligibility_is_required_for_new_report_not_rewritten_into_history(owned):
    v = owned
    grant_member(v)
    first = ownership(v).json()
    saved = assign(v, {**v["assignment_input"], "parent_revision_id": first["revision_id"], "parent_revision_hash": first["revision_hash"],
        "assignments": [{**item, "owner_actor_id": v["member"]["id"]} for item in v["assignment_input"]["assignments"]]}).json()
    assert saved["status"] == "completed", saved
    pin = saved["result"]["build_gap_ownership"]
    body = {**v["owned_input"], "ownership_pin": {key: pin[key] for key in v["owned_input"]["ownership_pin"]}}
    command = assess(v, body).json()
    assert command["status"] == "completed", command
    original = report(v, command["id"]).json()
    with session_scope() as session:
        session.execute(update(UserIdentityRecord).where(UserIdentityRecord.user_id == v["member"]["id"]).values(status="suspended"))
    assert assess(v, body).json()["status"] == "failed"
    assert report(v, command["id"]).json() == original


def test_historical_refinement_reauthorizes_source_and_rejects_bad_assignment_receipt(owned):
    v = owned
    command = assess(v, v["owned_input"]).json()
    assert command["status"] == "completed", command
    grant_member(v)
    policy(v, (v["member"]["id"],))
    assert report(v, command["id"], v["member_headers"]).status_code == 200
    policy(v)
    denied = report(v, command["id"], v["member_headers"])
    assert denied.status_code == 403 and "ownership" not in denied.text
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, v["assignment"]["id"])
        row.result_payload = {**row.result_payload, "build_gap_ownership": {
            **row.result_payload["build_gap_ownership"], "revision_hash": "sha256:" + "0" * 64}}
    broken = report(v, command["id"])
    assert broken.status_code == 502 and '"gaps":' not in broken.text, broken.text
