"""Real PG/MinIO canonical health history; native commands remain protocol specimens."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib
from types import SimpleNamespace
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import inspect, select, text, update

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.quality_loop.run_plan_environments import RunPlanEnvironmentQuery
from apps.api.app.domain.quality_loop.environment_health_record import (
    HEALTH_RECORD_TOOL, HEALTH_RECORD_QUERY_TOOL, HEALTH_RECORD_EVENT, HEALTH_EVENT_FIELDS,
)
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.environment_health_models import EnvironmentHealthRecord as Record
from apps.api.app.infrastructure.persistence.environment_observation_models import EnvironmentObservationRecord as InventoryRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.runner.owned_target_health import OwnedTargetHealthInspector
from apps.api.tests.test_owned_target_environment import spec
from apps.api.tests.test_owned_target_health import HealthCommands
from apps.api.tests.test_run_plan_builds_api import (
    base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping, native_scripts,
    prepared_binding, submit_binding, read_binding,
)
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, confirm, count
from apps.api.tests.test_source_access_api import policy as restrict_source


def test_canonical_health_original_bytes_confirmation_history_and_atomic_ledger(native_scripts, spec, monkeypatch):
    v = native_scripts
    owned = replace(spec, project_id=v["project_id"])
    environment = {"environment_id": owned.environment_id, "kind": "local", "base_url": "http://127.0.0.1:8080",
        "inventory_hash": owned.digest, "isolation": "Original operator-owned health protocol specimen"}
    v = prepared_binding(v, monkeypatch, environment=environment)
    bound = completed(submit_binding(v))
    binding_id = bound["result"]["object_refs"][0].split(":", 1)[1]
    binding = read_binding(v, binding_id).json()
    request = {"project_id": v["project_id"], "run_plan_id": v["original_plan"]["metadata"]["run_plan_id"],
        "run_plan_artifact_hash": v["original_plan"]["metadata"]["artifact_hash"], "build_binding_id": binding_id,
        "build_binding_artifact_hash": binding["metadata"]["artifact_hash"]}
    commands = HealthCommands(owned)
    commands.body = binding["metadata"]["target_artifact_hash"][7:].encode() + b"  /app/target.jar\n"
    native = OwnedTargetHealthInspector(owned, command=commands)
    def policy(project, environment_id, *, require_work):
        assert (project, environment_id) == (owned.project_id, owned.environment_id)
        require_work()
        return owned.digest
    def inspect_health(project, environment_id, artifact_hash, *, require_work):
        assert (project, environment_id) == (owned.project_id, owned.environment_id)
        return native.inspect(artifact_hash, require_work=require_work)
    port = SimpleNamespace(policy_digest=policy, inspect_health=inspect_health)
    monkeypatch.setattr(app.state.container.run_plan_environment_health, "health", port)
    service = app.state.container.environment_health_records
    pending = invoke(v, HEALTH_RECORD_TOOL, request, key=uuid4().hex)
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    assert not commands.calls and count(v, Record) == 0
    with session_scope() as session:
        original = session.get(ToolInvocationRecord, pending.json()["id"])
        payload = {**original.input_payload, "confirmed_by_user": True, "confirmed_actor_id": v["owner"]["id"],
            "confirmed_at": (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()}
        session.execute(update(ToolInvocationRecord).where(ToolInvocationRecord.id == original.id).values(input_payload=payload, status="running"))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(ValueError):
            service.record(RunPlanEnvironmentQuery.model_validate(request), invocation_id=pending.json()["id"],
                recorded_at=datetime.now(timezone.utc).isoformat())
    assert not commands.calls and count(v, Record) == 0

    append = EventOutboxRepository.append
    fault_hits = []
    def late_fault(repository, event, **kwargs):
        result = append(repository, event, **kwargs)
        if event.event_type == HEALTH_RECORD_EVENT:
            session = kwargs["session"]
            session.flush()
            assert session.get(Record, event.entity_id) is not None
            assert session.scalar(select(AuditEventRecord).where(AuditEventRecord.action == HEALTH_RECORD_EVENT,
                AuditEventRecord.entity_id == event.entity_id)) is not None
            assert session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_id == event.event_id)) is not None
            fault_hits.append(event.entity_id)
            raise RuntimeError("late original health ledger fault")
        return result
    monkeypatch.setattr(EventOutboxRepository, "append", late_fault)
    failed = invoke(v, HEALTH_RECORD_TOOL, request, key=uuid4().hex)
    failed = confirm(v, failed.json())
    assert failed.status_code == 200 and failed.json()["status"] == "failed", failed.text
    assert len(fault_hits) == 1 and count(v, Record) == 0
    with session_scope() as session:
        assert session.scalar(select(AuditEventRecord).where(AuditEventRecord.action == HEALTH_RECORD_EVENT,
            AuditEventRecord.entity_id == fault_hits[0])) is None
        assert session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_type == HEALTH_RECORD_EVENT,
            SSEEventOutboxRecord.entity_id == fault_hits[0])) is None
    monkeypatch.setattr(EventOutboxRepository, "append", append)

    saved = invoke(v, HEALTH_RECORD_TOOL, request, key=uuid4().hex)
    saved = completed(confirm(v, saved.json()))
    receipt = saved["result"]["run_plan_health_record"]
    metadata = receipt["metadata"]
    record_id = metadata["record_id"]
    assert metadata["dependency_health_verified"] is metadata["target_health_verified"] is True
    assert metadata["execution_authorized"] is metadata["environment_fully_verified"] is metadata["business_coverage_verified"] is False
    assert metadata["automated_count"] == metadata["executed_on_target_count"] == metadata["passed_count"] == 0
    assert "response_base64" not in str(saved) and "container_id" not in str(saved) and "127.0.0.1" not in str(saved)
    assert count(v, Record) == 1 and count(v, InventoryRecord) == 0
    calls = len(commands.calls)
    url = f"/v1/projects/{v['project_id']}/quality/run-plan-health/{record_id}"
    view = v["client"].get(url, headers=v["headers"])
    assert view.status_code == 200 and view.headers["cache-control"] == "private, no-store", view.text
    assert view.json()["archive"]["observation"]["inventory"]["dependency_health_verified"] is False
    assert len(view.json()["archive"]["observation"]["checks"]) == 3 and view.json()["metadata"] == metadata
    monkeypatch.setattr(app.state.container.run_plan_environment_health, "health", None)
    queried = completed(invoke(v, HEALTH_RECORD_QUERY_TOOL, {"project_id": v["project_id"], "record_id": record_id}))
    assert queried["result"]["run_plan_health_record"] == receipt and len(commands.calls) == calls
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert service.record(RunPlanEnvironmentQuery.model_validate(request), invocation_id=saved["id"],
            recorded_at=datetime.now(timezone.utc).isoformat()) == metadata
        events = EventOutboxRepository().list_after(stream_kind="conversation",
            stream_id=v["conversation"].json()["id"], after_event_id=None, limit=500)
    events = [item for item in events if item.event_type == HEALTH_RECORD_EVENT]
    assert len(events) == 1 and events[0].patch == {key: metadata[key] for key in HEALTH_EVENT_FIELDS}
    assert "response_base64" not in str(events[0]) and len(commands.calls) == calls

    with engine.connect() as connection:
        schema = inspect(connection)
        assert {item["name"] for item in schema.get_columns(Record.__tablename__)} == {column.name for column in Record.__table__.columns}
        actual = {(tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"]))
            for item in schema.get_foreign_keys(Record.__tablename__)}
        expected = {(tuple(element.parent.name for element in constraint.elements),
            next(iter(constraint.elements)).column.table.name, tuple(element.column.name for element in constraint.elements))
            for constraint in Record.__table__.foreign_key_constraints}
        assert actual == expected
    for operation in ("UPDATE quality_run_plan_health_records SET status='recorded' WHERE record_id=:id",
            "DELETE FROM quality_run_plan_health_records WHERE record_id=:id"):
        with engine.connect() as connection:
            transaction = connection.begin()
            with pytest.raises(Exception): connection.execute(text(operation), {"id": record_id})
            transaction.rollback()
    migration = importlib.import_module("apps.api.migrations.versions.0106_environment_health")
    with engine.connect() as connection:
        transaction = connection.begin()
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="Cannot discard"): migration.downgrade()
        transaction.rollback()

    original_read = service.artifacts.read
    monkeypatch.setattr(service.artifacts, "read", lambda *args, **kwargs: {"schema": "corrupt"})
    damaged = v["client"].get(url, headers=v["headers"])
    assert damaged.status_code == 502 and damaged.headers["cache-control"] == "private, no-store", damaged.text
    damaged_receipt = v["client"].get(f"/v1/tool-invocations/{queried['id']}", headers=v["headers"])
    assert damaged_receipt.status_code == 502, damaged_receipt.text
    monkeypatch.setattr(service.artifacts, "read", original_read)
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    granted = v["client"].put(membership, headers=v["headers"], json={"role": "qa_lead"})
    assert granted.status_code == 200, granted.text
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 200
    restrict_source(v)
    def forbidden(*args, **kwargs): pytest.fail("source ACL must precede private health bytes")
    monkeypatch.setattr(service.artifacts, "read", forbidden)
    denied = v["client"].get(url, headers=v["member_headers"])
    assert denied.status_code == 403 and denied.headers["cache-control"] == "private, no-store", denied.text
    assert len(commands.calls) == calls
