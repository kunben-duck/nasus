import json

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.system_image.gap_ownership import ASSIGN_GAPS_TOOL
from apps.api.app.infrastructure.persistence.db_models import (AgentGoalRecord, AuditEventRecord,
    SSEEventOutboxRecord, ToolInvocationRecord, UserIdentityRecord)
from apps.api.app.infrastructure.persistence.gap_ownership_models import BuildGapOwnershipRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_build_completion_api import completion, submit as assess, report
from apps.api.tests.test_investigation_api import investigation
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import grant_member, policy
from apps.api.tests.test_structure_build_api import confirm


def ownership(v):
    return v["client"].get(f"/v1/projects/{v['project_id']}/system-image/build-completions/{v['assessment']['id']}/gap-ownership",
        headers=v["headers"])


@pytest.fixture
def gaps(completion):
    v = completion
    v["assessment"] = assess(v).json()
    assert v["assessment"]["status"] == "completed", v["assessment"]
    v["original_report"] = report(v, v["assessment"]["id"]).json()
    response = ownership(v)
    assert response.status_code == 200, response.text
    v["ownership"] = response.json()
    v["assignment_input"] = {"project_id": v["project_id"], "completion_invocation_id": v["assessment"]["id"],
        "completion_report_hash": v["assessment"]["result"]["build_completion"]["report_hash"],
        "expected_goal": v["completion_input"]["expected_goal"], "parent_revision_id": None, "parent_revision_hash": None,
        "assignments": [{"gap_id": gap["gap_id"], "owner_actor_id": v["owner"]["id"],
            "reason": "Reviewer accepts responsibility to investigate this unresolved gap."} for gap in v["ownership"]["gaps"]]}
    return v


def assign(v, body=None, *, key=None, confirmed=True, headers=None):
    response = v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json={
        "tool_id": ASSIGN_GAPS_TOOL, "conversation_id": v["conversation"].json()["id"],
        "input": body if body is not None else v["assignment_input"], "idempotency_key": key})
    if response.status_code != 200:
        return response
    if confirmed and response.json()["status"] == "waiting_confirmation":
        return v["client"].post(f"/v1/tool-invocations/{response.json()['id']}/confirm", headers=headers or v["headers"])
    return response


def rows(v):
    with session_scope() as session:
        return session.scalar(select(func.count()).select_from(BuildGapOwnershipRecord).where(
            BuildGapOwnershipRecord.project_id == v["project_id"]))


def test_independent_confirmation_full_inventory_atomic_audit_and_replay(gaps):
    v = gaps
    pending = assign(v, confirmed=False, key="original-gap-assignment")
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    assert rows(v) == 0
    item = confirm(v, pending.json()["id"])
    assert item["status"] == "completed", item
    receipt = item["result"]["build_gap_ownership"]
    current = ownership(v)
    assert current.status_code == 200 and current.headers["cache-control"] == "private, no-store", current.text
    view = current.json()
    assert view["revision_id"] == receipt["revision_id"] and view["revision_hash"] == receipt["revision_hash"]
    assert all(gap["ownership_status"] == "confirmed" and gap["resolution_status"] == "unresolved" for gap in view["gaps"])
    assert len(view["history"]) == 1 and not any(view[key] for key in ("goal_completed", "publication_authorized", "execution_authorized"))
    assert report(v, v["assessment"]["id"]).json() == v["original_report"]
    assert v["client"].get(f"/v1/agent-goals/{v['assignment_input']['expected_goal']['id']}", headers=v["headers"]).json() == v["assignment_input"]["expected_goal"]
    assert assign(v, key="original-gap-assignment").json()["id"] == item["id"]
    assert rows(v) == 1
    with session_scope() as session:
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == receipt["revision_id"])).all()
        audit = session.scalars(select(AuditEventRecord).where(AuditEventRecord.entity_id == receipt["revision_id"])).all()
    assert len(events) == len(audit) == 1
    public = json.dumps(item) + json.dumps([event.event_payload for event in events])
    assert not any(secret in public for secret in ("orders.py", "class Orders", "s3://", '"source_scans":', '"gaps":'))
    for mutation in (update(BuildGapOwnershipRecord).values(revision_hash="changed"), delete(BuildGapOwnershipRecord)):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(mutation.where(BuildGapOwnershipRecord.revision_id == receipt["revision_id"]))


@pytest.mark.parametrize("failure", ["hash", "goal", "missing", "duplicate", "extra", "foreign_owner", "unknown_field"])
def test_assignment_cannot_invent_gaps_scope_checkpoint_or_owners(gaps, failure):
    v = gaps
    body = json.loads(json.dumps(v["assignment_input"]))
    if failure == "hash":
        body["completion_report_hash"] = "sha256:" + "0" * 64
    elif failure == "goal":
        body["expected_goal"]["summary"] = "invented"
    elif failure == "missing":
        body["assignments"] = body["assignments"][:-1]
    elif failure == "duplicate":
        body["assignments"].append(body["assignments"][0])
    elif failure == "extra":
        body["assignments"][0]["gap_id"] = "gap_" + "0" * 64
    elif failure == "foreign_owner":
        body["assignments"][0]["owner_actor_id"] = v["member"]["id"]
    else:
        body["resolve_all"] = True
    response = assign(v, body)
    assert response.status_code == 403 or response.status_code == 200 and response.json()["status"] == "failed", response.text
    assert rows(v) == 0


def test_reassignment_requires_exact_current_parent_and_preserves_old_owners(gaps):
    v = gaps
    first = assign(v)
    assert first.json()["status"] == "completed", first.text
    saved = ownership(v).json()
    grant_member(v)
    body = {**v["assignment_input"], "parent_revision_id": saved["revision_id"], "parent_revision_hash": saved["revision_hash"],
        "assignments": [{**item, "owner_actor_id": v["member"]["id"]} for item in v["assignment_input"]["assignments"]]}
    second = assign(v, body)
    assert second.json()["status"] == "completed", second.text
    current = ownership(v).json()
    assert current["revision_number"] == 2 and len(current["history"]) == 2
    assert all(item["owner_actor_id"] == v["owner"]["id"] for item in current["history"][0]["assignments"])
    assert all(item["owner_actor_id"] == v["member"]["id"] for item in current["gaps"])
    with actor_scope(UserProfile.model_validate(v["owner"])):
        original = app.state.container.tool_evidence.describe(first.json()["id"], v["project_id"])
    assert original["revision_id"] == saved["revision_id"] and not original["is_current_revision"]
    assert all(item["owner_actor_id"] == v["owner"]["id"] for item in original["gaps"])
    stale = assign(v, body)
    assert stale.json()["status"] == "failed" and rows(v) == 2, stale.text
    with session_scope() as session:
        session.execute(update(UserIdentityRecord).where(UserIdentityRecord.user_id == v["member"]["id"]).values(status="suspended"))
    current = ownership(v).json()
    assert all(item["ownership_status"] == "owner_unavailable" and item["owner_actor_id"] == v["member"]["id"] for item in current["gaps"])


def test_checkpoint_change_between_prepare_and_confirm_does_not_commit(gaps):
    v = gaps
    pending = assign(v, confirmed=False).json()
    with session_scope() as session:
        session.execute(update(AgentGoalRecord).where(AgentGoalRecord.id == v["assignment_input"]["expected_goal"]["id"]).values(summary="changed during confirmation"))
    result = confirm(v, pending["id"])
    assert result["status"] == "failed" and rows(v) == 0
    assert ownership(v).status_code == 200


@pytest.mark.parametrize("failure", ["outbox", "authorization"])
def test_late_failure_rolls_back_owners_audit_and_event(gaps, monkeypatch, failure):
    v = gaps
    from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
    original = EventOutboxRepository.append
    def append(self, event, **kwargs):
        if event.event_type == "system_image.build.gaps.assigned":
            if failure == "outbox":
                raise RuntimeError("injected outbox failure")
            from apps.api.app.domain.system_image.source_access import StaleSourceAccessScope
            app.state.container.build_plans.authorization.require_current = lambda scope: (_ for _ in ()).throw(StaleSourceAccessScope("changed"))
        return original(self, event, **kwargs)
    # Patch the instance through monkeypatch too so the test never leaks it.
    monkeypatch.setattr(app.state.container.build_plans.authorization, "require_current", app.state.container.build_plans.authorization.require_current)
    monkeypatch.setattr(EventOutboxRepository, "append", append)
    response = assign(v)
    assert response.status_code == 403 or response.status_code == 200 and response.json()["status"] == "failed", response.text
    assert rows(v) == 0
    with session_scope() as session:
        assert not session.scalar(select(AuditEventRecord.id).where(AuditEventRecord.action == "system_image.build.gaps.assigned",
            AuditEventRecord.agent_goal_id == v["assignment_input"]["expected_goal"]["id"]))


def test_history_and_assignment_commands_recheck_source_access(gaps):
    v = gaps
    item = assign(v).json()
    assert item["status"] == "completed", item
    grant_member(v)
    policy(v, (v["member"]["id"],))
    url = f"/v1/projects/{v['project_id']}/system-image/build-completions/{v['assessment']['id']}/gap-ownership"
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 200
    policy(v)
    denied = v["client"].get(url, headers=v["member_headers"])
    assert denied.status_code == 403 and '"gaps"' not in denied.text
    assert v["client"].get(f"/v1/tool-invocations/{item['id']}", headers=v["member_headers"]).status_code == 403


def test_owner_options_are_active_project_scoped_and_require_current_source_access(gaps):
    v = gaps
    url = f"/v1/projects/{v['project_id']}/system-image/build-completions/{v['assessment']['id']}/gap-owners"
    response = v["client"].get(url, headers=v["headers"])
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store", response.text
    assert v["owner"]["id"] in {item["actor_id"] for item in response.json()}
    assert all(set(item) == {"actor_id", "display_name"} for item in response.json())
    grant_member(v)
    policy(v, (v["member"]["id"],))
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 403
    with session_scope() as session:
        session.execute(update(UserIdentityRecord).where(UserIdentityRecord.user_id == v["member"]["id"]).values(status="suspended"))
    assert v["member"]["id"] not in {item["actor_id"] for item in v["client"].get(url, headers=v["headers"]).json()}


@pytest.mark.parametrize("mutation", ["owner", "expired", "future", "actor", "receipt"])
def test_confirmation_and_replay_do_not_accept_changed_ownership_provenance(gaps, mutation):
    from datetime import datetime, timedelta, timezone
    v = gaps
    if mutation == "receipt":
        item = assign(v).json()
        assert item["status"] == "completed", item
        with session_scope() as session:
            row = session.get(ToolInvocationRecord, item["id"])
            row.result_payload = {**row.result_payload, "build_gap_ownership": {
                **row.result_payload["build_gap_ownership"], "revision_hash": "sha256:" + "0" * 64}}
        with actor_scope(UserProfile.model_validate(v["owner"])):
            with pytest.raises(Exception, match="replay verification"):
                app.state.container.tool_evidence.describe(item["id"], v["project_id"])
        denied = ownership(v)
        assert denied.status_code == 502 and denied.json()["detail"]["error"]["code"] == "build_plan_integrity_failed"
        assert '"gaps"' not in denied.text
        return
    if mutation == "owner":
        grant_member(v)
        body = {**v["assignment_input"], "assignments": [{**item, "owner_actor_id": v["member"]["id"]}
            for item in v["assignment_input"]["assignments"]]}
        pending = assign(v, body, confirmed=False).json()
        with session_scope() as session:
            session.execute(update(UserIdentityRecord).where(UserIdentityRecord.user_id == v["member"]["id"]).values(status="suspended"))
        result = confirm(v, pending["id"])
    else:
        # Mutate at the repository boundary, after Runtime creates real consent.
        repository = app.state.container.gap_ownership.repository
        original = repository.record
        def record(request, **kwargs):
            with session_scope() as session:
                row = session.get(ToolInvocationRecord, kwargs["invocation_id"])
                body = dict(row.input_payload)
                if mutation == "actor":
                    body["confirmed_actor_id"] = v["member"]["id"]
                else:
                    body["confirmed_at"] = (datetime.now(timezone.utc) + timedelta(minutes=1 if mutation == "future" else -16)).isoformat()
                row.input_payload = body
            return original(request, **kwargs)
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(repository, "record", record)
            result = assign(v).json()
    assert result["status"] == "failed" and rows(v) == 0, result


def test_competing_confirmations_commit_only_one_complete_revision(gaps, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    v = gaps
    pending = [assign(v, key=f"competing-{i}", confirmed=False).json() for i in range(2)]
    assert all(item["status"] == "waiting_confirmation" for item in pending)
    repository = app.state.container.gap_ownership.repository
    original, barrier = repository.record, Barrier(2)
    def record(request, **kwargs):
        barrier.wait(timeout=20)
        return original(request, **kwargs)
    monkeypatch.setattr(repository, "record", record)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda item: confirm(v, item["id"]), pending))
    assert sorted(item["status"] for item in results) == ["completed", "failed"], results
    assert rows(v) == 1 and len(ownership(v).json()["history"]) == 1


@pytest.mark.parametrize("mutation", ["status", "conversation"])
def test_private_history_requires_its_exact_completed_canonical_command(gaps, mutation):
    v = gaps
    item = assign(v).json()
    assert item["status"] == "completed", item
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, item["id"])
        if mutation == "status":
            row.status = "failed"
        else:
            # A second valid conversation is still not the one consented to.
            conversation = v["client"].post("/v1/conversations", headers=v["headers"], json={
                "space_type": "knowledge", "space_id": v["project_id"], "project_id": v["project_id"],
                "title": "Other responsibility scope"})
            assert conversation.status_code == 200, conversation.text
            assert conversation.json()["id"] != v["conversation"].json()["id"]
            row.conversation_id = conversation.json()["id"]
    response = ownership(v)
    assert response.status_code == 502 and response.json()["detail"]["error"]["code"] == "build_plan_integrity_failed", response.text
    assert '"gaps"' not in response.text
