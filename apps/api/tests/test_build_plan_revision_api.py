from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from apps.api.app.main import app
from apps.api.app.domain.system_image.source_access import StaleSourceAccessScope
from apps.api.app.infrastructure.persistence.build_plan_models import BuildPlanRecord
from apps.api.app.infrastructure.persistence.build_plan_revision_models import BuildPlanRevisionRecord
from apps.api.app.infrastructure.persistence.db_models import AgentGoalRecord, AuditEventRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_agent_investigation_continuation import start_structure
from apps.api.tests.test_source_access_api import grant_member, policy


def capture_documents(v, tmp_path, *, tests=False):
    path = tmp_path / ("test-cases.csv" if tests else "requirements.md")
    path.write_text("id,title,expected_result\nTC-1,Submit order,Order is accepted\n" if tests else
                    "# US-1 Submit order\n\n## Acceptance criteria\n- An accepted order receives a receipt.\n")
    v["invoke"]("system_image.sources.register", {"source_specs": [
        {"source_type": "test_asset" if tests else "us_doc", "source_uri": str(path)}]})
    v["invoke"]("system_image.sources.ingest")
    return SourceSnapshotRepository().latest_manifest(v["project_id"]).manifest_id


def body(v, fixed, goal, manifest_id, **changes):
    return {"project_id": v["project_id"], "goal_id": goal["id"], "root_plan_id": fixed["plan_id"],
        "from_plan_id": fixed["plan_id"], "from_plan_digest": fixed["plan_digest"],
        "source_manifest_id": manifest_id, "expected_goal": goal, **changes}


def prepare(v, payload, key="revision-one"):
    response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "conversation_id": v["conversation"].json()["id"], "tool_id": "system_image.build.plan.revise",
        "idempotency_key": key, "input": payload})
    assert response.status_code == 200, response.text
    return response.json()


def confirm(v, command):
    response = v["client"].post(f"/v1/tool-invocations/{command['id']}/confirm", headers=v["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def history(v, fixed, goal, headers=None):
    return v["client"].get(f"/v1/projects/{v['project_id']}/system-image/build-plans/{fixed['plan_id']}/revisions",
        params={"goal_id": goal["id"]}, headers=headers or v["headers"])


def test_real_same_goal_enrichment_is_append_only_and_does_not_transfer_execution(evidence_api, tmp_path):
    v = evidence_api
    fixed, goal = start_structure(v)
    original = deepcopy(goal)
    manifest_id = capture_documents(v, tmp_path)
    pending = prepare(v, body(v, fixed, goal, manifest_id))
    assert pending["status"] == "waiting_confirmation"
    assert history(v, fixed, goal).json() == []
    saved = confirm(v, pending)
    assert saved["status"] == "completed", saved
    first = history(v, fixed, goal)
    assert first.status_code == 200 and first.headers["cache-control"] == "private, no-store", first.text
    item, = first.json()
    revision = item["revision"]
    assert revision["goal_id"] == goal["id"] and revision["from_plan_id"] == fixed["plan_id"]
    assert revision["source_manifest_id"] == manifest_id
    assert revision["execution_authorized"] is False and revision["publication_authorized"] is False
    new_url = f"/v1/projects/{v['project_id']}/system-image/build-plans/{revision['plan_id']}"
    new = v["client"].get(new_url, headers=v["headers"]).json()
    assert new["execution_authorizations"] == [] and new["structural_artifacts"] == []
    assert new["proposal"]["intent"]["mode"] == "enrich"
    assert v["client"].get(f"/v1/agent-goals/{goal['id']}", headers=v["headers"]).json() == original
    assert prepare(v, body(v, fixed, goal, manifest_id))["id"] == pending["id"]
    assert history(v, fixed, goal).json() == first.json()
    next_manifest = capture_documents(v, tmp_path, tests=True)
    stale = confirm(v, prepare(v, body(v, fixed, goal, next_manifest), key="stale-parent"))
    assert stale["status"] == "failed"
    second_payload = body(v, fixed, goal, next_manifest, from_plan_id=revision["plan_id"],
        from_plan_digest=revision["plan_digest"], parent_revision_id=revision["revision_id"],
        parent_revision_hash=item["revision_hash"])
    second = confirm(v, prepare(v, second_payload, key="revision-two"))
    assert second["status"] == "completed", second
    items = history(v, fixed, goal).json()
    assert len(items) == 2 and items[0] == item and items[1]["revision"]["revision_number"] == 2
    assert items[1]["revision"]["goal_id"] == original["id"]
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(AgentGoalRecord).where(
            AgentGoalRecord.conversation_id == goal["conversation_id"])) == 1
        assert session.scalar(select(func.count()).select_from(AuditEventRecord).where(
            AuditEventRecord.agent_goal_id == goal["id"], AuditEventRecord.action == "system_image.build.plan.revised")) == 2


@pytest.mark.parametrize("change", ["budget", "steps", "status"])
def test_stale_displayed_goal_cannot_commit_a_revision(evidence_api, tmp_path, change):
    from apps.api.app.infrastructure.persistence.build_tool_budget_repository import BuildToolBudgetRepository

    v = evidence_api
    fixed, goal = start_structure(v)
    pending = prepare(v, body(v, fixed, goal, capture_documents(v, tmp_path)))
    with session_scope() as session:
        row = session.get(AgentGoalRecord, goal["id"])
        if change == "budget":
            row.max_steps += 1
        elif change == "status":
            row.status, row.pause_reason = "cancelled", "user_interrupt"
        else:
            steps = deepcopy(row.steps)
            steps[-1]["title"] = "Changed review checkpoint"
            row.steps = steps
    before = BuildToolBudgetRepository().inspect(goal["id"])
    result = confirm(v, pending)
    assert result["status"] == "failed", result
    assert history(v, fixed, goal).json() == []
    assert BuildToolBudgetRepository().inspect(goal["id"]) == before


def test_revocation_and_late_scope_failure_preserve_private_history_and_roll_back(evidence_api, tmp_path, monkeypatch):
    v = evidence_api
    fixed, goal = start_structure(v)
    payload = body(v, fixed, goal, capture_documents(v, tmp_path))
    repository = app.state.container.build_plans.revisions.repository
    original = repository.record

    def revoke_before_commit(*args, **kwargs):
        def revoked():
            raise StaleSourceAccessScope("private revoked source")
        return original(*args, **{**kwargs, "require_current": revoked})

    with session_scope() as session:
        before = session.scalar(select(func.count()).select_from(BuildPlanRecord).where(BuildPlanRecord.project_id == v["project_id"]))
    monkeypatch.setattr(repository, "record", revoke_before_commit)
    assert confirm(v, prepare(v, payload))["status"] == "failed"
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(BuildPlanRecord).where(BuildPlanRecord.project_id == v["project_id"])) == before
        assert session.scalar(select(func.count()).select_from(BuildPlanRevisionRecord).where(BuildPlanRevisionRecord.goal_id == goal["id"])) == 0
    monkeypatch.setattr(repository, "record", original)
    saved = confirm(v, prepare(v, payload, key="fresh-revision"))
    assert saved["status"] == "completed", saved
    assert history(v, fixed, goal, v["member_headers"]).status_code == 403
    grant_member(v)
    assert history(v, fixed, goal, v["member_headers"]).status_code == 200
    policy(v)
    denied = history(v, fixed, goal, v["member_headers"])
    assert denied.status_code == 403 and "private revoked" not in denied.text
    assert v["client"].get(f"/v1/tool-invocations/{saved['id']}", headers=v["member_headers"]).status_code == 403


def test_concurrent_confirmations_cannot_fork_the_original_goal_revision_chain(evidence_api, tmp_path):
    v = evidence_api
    fixed, goal = start_structure(v)
    payload = body(v, fixed, goal, capture_documents(v, tmp_path))
    first, second = prepare(v, payload, key="concurrent-a"), prepare(v, payload, key="concurrent-b")
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda command: confirm(v, command), (first, second)))
    assert sorted(value["status"] for value in results) == ["completed", "failed"]
    items = history(v, fixed, goal).json()
    assert len(items) == 1
    assert v["client"].get(f"/v1/agent-goals/{goal['id']}", headers=v["headers"]).json() == goal


def test_completed_revision_read_rejects_rebound_source_parent_and_result(evidence_api, tmp_path):
    v = evidence_api
    fixed, goal = start_structure(v)
    saved = confirm(v, prepare(v, body(v, fixed, goal, capture_documents(v, tmp_path))))
    assert saved["status"] == "completed", saved
    newer_manifest = capture_documents(v, tmp_path, tests=True)
    url = f"/v1/tool-invocations/{saved['id']}"
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, saved["id"])
        original_input, original_result = deepcopy(row.input_payload), deepcopy(row.result_payload)
    for change in ("source", "parent", "result"):
        with session_scope() as session:
            row = session.get(ToolInvocationRecord, saved["id"])
            payload, result = deepcopy(original_input), deepcopy(original_result)
            if change == "source":
                payload["source_manifest_id"] = newer_manifest
            elif change == "parent":
                payload.update(parent_revision_id="wrong-parent", parent_revision_hash="sha256:" + "a" * 64)
            else:
                result["object_refs"] = ["build_plan_revision:other", "build_plan:other"]
            row.input_payload, row.result_payload = payload, result
        reads = [(url, {}), ("/v1/tool-invocations", {"tool_id": saved["tool_id"]}),
            ("/v1/audit-events", {"tool_invocation_id": saved["id"]})]
        for endpoint, params in reads:
            response = v["client"].get(endpoint, headers=v["headers"], params=params)
            assert response.status_code == 502, (change, response.text)
            assert saved["id"] not in response.text and newer_manifest not in response.text
        assert len(history(v, fixed, goal).json()) == 1
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, saved["id"])
        row.input_payload, row.result_payload = original_input, original_result
    assert v["client"].get(url, headers=v["headers"]).status_code == 200
    restored = v["client"].get("/v1/tool-invocations", headers=v["headers"], params={"tool_id": saved["tool_id"]})
    assert restored.status_code == 200 and any(item["id"] == saved["id"] for item in restored.json())


def test_committed_revision_recovery_reuses_exact_fact_and_pg_rejects_mutation(evidence_api, tmp_path):
    v = evidence_api
    fixed, goal = start_structure(v)
    payload = body(v, fixed, goal, capture_documents(v, tmp_path))
    completed = confirm(v, prepare(v, payload))
    assert completed["status"] == "completed"
    original, = history(v, fixed, goal).json()
    # Simulate loss of the Runtime completion acknowledgement after the PG fact committed.
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, completed["id"])
        row.status = "running"
    from apps.api.app.application.platform.actor_context import actor_scope
    from apps.api.app.application.system_image.build_plan_revisions import BuildPlanRevisionInput
    from apps.api.app.application.platform.account_models import UserProfile
    actor = UserProfile.model_validate(v["owner"])
    with actor_scope(actor):
        recovered = app.state.container.build_plans.revisions.revise(BuildPlanRevisionInput.model_validate(payload),
            invocation_id=completed["id"], created_at=original["revision"]["created_at"])
    assert recovered.revision.revision_id == original["revision"]["revision_id"]
    assert history(v, fixed, goal).json() == [original]
    for operation in ("update", "delete"):
        with pytest.raises(DBAPIError), session_scope() as session:
            row = session.get(BuildPlanRevisionRecord, recovered.revision.revision_id)
            if operation == "update":
                row.revision_hash = "tampered"
            else:
                session.delete(row)
            session.flush()
    assert history(v, fixed, goal).json() == [original]


def test_revision_migration_retains_populated_history_and_matches_orm(evidence_api, tmp_path, monkeypatch):
    import importlib
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import inspect, text
    from apps.api.app.infrastructure.persistence.database import engine
    v = evidence_api
    fixed, goal = start_structure(v)
    saved = confirm(v, prepare(v, body(v, fixed, goal, capture_documents(v, tmp_path))))
    assert saved["status"] == "completed"
    revision_id = history(v, fixed, goal).json()[0]["revision"]["revision_id"]
    migration = importlib.import_module("apps.api.migrations.versions.0086_build_plan_revisions")
    assert engine.url.database.startswith("nasus_test_")
    schema = "nasus_test_plan_revisions_" + uuid4().hex
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            columns = {item["name"]: item for item in inspect(connection).get_columns("image_build_plan_revisions", schema=schema)}
            assert columns.keys() == set(BuildPlanRevisionRecord.__table__.columns.keys())
            for column in BuildPlanRevisionRecord.__table__.columns:
                assert columns[column.name]["nullable"] == column.nullable
                assert columns[column.name]["type"]._type_affinity is column.type._type_affinity
            migration.downgrade()
            migration.upgrade()
            connection.execute(text("INSERT INTO image_build_plan_revisions SELECT * FROM public.image_build_plan_revisions WHERE revision_id = :id"), {"id": revision_id})
            with pytest.raises(RuntimeError, match="populated"):
                migration.downgrade()
            assert connection.scalar(text("SELECT count(*) FROM image_build_plan_revisions")) == 1
        finally:
            transaction.rollback()
