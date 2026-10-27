"""Real canonical PG/private MinIO history; model/oracles remain protocol specimens."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import inspect, select, text, update

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.quality_loop.run_plan_locators import RunPlanLocatorQuery
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_locator_record import (
    LOCATOR_RECORD_TOOL, LOCATOR_RECORD_QUERY_TOOL, LOCATOR_RECORD_EVENT, LOCATOR_EVENT_FIELDS,
)
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.http_locator_models import HttpLocatorRecord as Record
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_run_plans_api import (
    base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping, native_scripts,
    reviewed_plan_inputs, preview, submit, read, select_binding_scripts,
)
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, confirm, count
from apps.api.tests.test_source_access_api import policy as restrict_source


def test_canonical_locator_original_bytes_confirmation_readonly_history_and_atomic_ledger(native_scripts, monkeypatch):
    v = native_scripts
    select_binding_scripts(v)
    _, _, _, selection = reviewed_plan_inputs(v)
    selection = selection.model_copy(update={"policy_revision": "nasus.run-plan.v2"})
    prepared = completed(submit(v, preview(v, selection).json()["request"]))
    ident = prepared["result"]["object_refs"][0].split(":", 1)[1]
    plan = read(v, ident).json()
    request = {"project_id": v["project_id"], "run_plan_id": ident, "run_plan_artifact_hash": plan["metadata"]["artifact_hash"]}
    service = app.state.container.http_locator_records
    original_record, recording_errors = service.record, []
    def diagnosed_record(*args, **kwargs):
        try:
            return original_record(*args, **kwargs)
        except Exception as exc:
            recording_errors.append((type(exc).__name__, str(exc)))
            raise
    monkeypatch.setattr(service, "record", diagnosed_record)
    original_inspect, calls = service.locators.inventory.inspect, []
    def inspected(*args, **kwargs):
        calls.append("parse")
        return original_inspect(*args, **kwargs)
    monkeypatch.setattr(service.locators.inventory, "inspect", inspected)
    pending = invoke(v, LOCATOR_RECORD_TOOL, request, key=uuid4().hex)
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    assert not calls and count(v, Record) == 0
    with session_scope() as session:
        original = session.get(ToolInvocationRecord, pending.json()["id"])
        payload = {**original.input_payload, "confirmed_by_user": True, "confirmed_actor_id": v["owner"]["id"],
            "confirmed_at": (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()}
        session.execute(update(ToolInvocationRecord).where(ToolInvocationRecord.id == original.id).values(input_payload=payload, status="running"))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(ValueError): service.record(RunPlanLocatorQuery.model_validate(request), invocation_id=pending.json()["id"], recorded_at=datetime.now(timezone.utc).isoformat())
    assert not calls and count(v, Record) == 0
    append, fault_hits = EventOutboxRepository.append, []
    def late_fault(repository, event, **kwargs):
        result = append(repository, event, **kwargs)
        if event.event_type == LOCATOR_RECORD_EVENT:
            session = kwargs["session"]
            session.flush()
            assert session.get(Record, event.entity_id) is not None
            assert session.scalar(select(AuditEventRecord).where(AuditEventRecord.entity_id == event.entity_id)) is not None
            assert session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_id == event.event_id)) is not None
            fault_hits.append(event.entity_id)
            raise RuntimeError("late original locator ledger fault")
        return result
    monkeypatch.setattr(EventOutboxRepository, "append", late_fault)
    failed = invoke(v, LOCATOR_RECORD_TOOL, request, key=uuid4().hex)
    failed = confirm(v, failed.json())
    assert failed.status_code == 200 and failed.json()["status"] == "failed", failed.text
    assert len(fault_hits) == 1 and count(v, Record) == 0, recording_errors
    with session_scope() as session:
        assert session.scalar(select(AuditEventRecord).where(AuditEventRecord.entity_id == fault_hits[0])) is None
        assert session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == fault_hits[0])) is None
    monkeypatch.setattr(EventOutboxRepository, "append", append)
    pending = invoke(v, LOCATOR_RECORD_TOOL, request, key=uuid4().hex)
    saved = completed(confirm(v, pending.json()))
    receipt = saved["result"]["run_plan_locator_record"]
    metadata = receipt["metadata"]
    assert metadata["durable_locator_evidence_verified"] is metadata["source_bytes_verified"] is True
    assert metadata["runtime_locators_verified"] is metadata["execution_authorized"] is metadata["business_coverage_verified"] is False
    assert metadata["automated_count"] == metadata["executed_on_target_count"] == metadata["passed_count"] == 0
    assert count(v, Record) == 1 and len(calls) == 2
    assert "snippet_hash" not in str(saved) and "relative_path" not in str(saved)
    record_id = metadata["record_id"]
    url = f"/v1/projects/{v['project_id']}/quality/run-plan-locators/{record_id}"
    monkeypatch.setattr(service.locators.inventory, "inspect", lambda *a, **k: pytest.fail("history parsed source"))
    view = v["client"].get(url, headers=v["headers"])
    assert view.status_code == 200 and view.headers["cache-control"] == "private, no-store", view.text
    assert view.json()["metadata"] == metadata and view.json()["archive"]["report"]["source_pin"] == plan["artifact"]["plan"]["source_pin"]
    queried = completed(invoke(v, LOCATOR_RECORD_QUERY_TOOL, {"project_id": v["project_id"], "record_id": record_id}))
    assert queried["result"]["run_plan_locator_record"] == receipt
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert service.record(RunPlanLocatorQuery.model_validate(request), invocation_id=saved["id"], recorded_at="ignored") == metadata
        assert app.state.container.tool_evidence.describe(queried["id"], v["project_id"]) == receipt
        events = EventOutboxRepository().list_after(stream_kind="conversation", stream_id=v["conversation"].json()["id"], after_event_id=None, limit=500)
    facts = [event for event in events if event.event_type == LOCATOR_RECORD_EVENT]
    assert len(facts) == 1 and facts[0].patch == {key: metadata[key] for key in LOCATOR_EVENT_FIELDS}
    assert "relative_path" not in str(facts[0]) and "snippet_hash" not in str(facts[0])
    for event in (event for event in events if event.entity_id in {saved["id"], queried["id"]}):
        assert event.payload["tool_invocation"]["result"] is None and event.payload["tool_invocation"]["input_payload"] == {}
    with engine.connect() as connection:
        actual = {(tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"])) for item in inspect(connection).get_foreign_keys(Record.__tablename__)}
        expected = {(tuple(element.parent.name for element in constraint.elements), next(iter(constraint.elements)).column.table.name,
            tuple(element.column.name for element in constraint.elements)) for constraint in Record.__table__.foreign_key_constraints}
        assert actual == expected
    for operation in ("UPDATE quality_run_plan_locator_records SET status='recorded' WHERE record_id=:id", "DELETE FROM quality_run_plan_locator_records WHERE record_id=:id"):
        with engine.connect() as connection:
            transaction = connection.begin()
            with pytest.raises(Exception): connection.execute(text(operation), {"id": record_id})
            transaction.rollback()
    migration = importlib.import_module("apps.api.migrations.versions.0107_http_locator_records")
    with engine.connect() as connection:
        transaction = connection.begin()
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="Cannot discard"): migration.downgrade()
        transaction.rollback()
    damaged = deepcopy(queried["result"])
    damaged["run_plan_locator_record"]["metadata"]["report_hash"] = acceptance_digest("forged-tool-history")
    with session_scope() as session: session.get(ToolInvocationRecord, queried["id"]).result_payload = damaged
    rejected = v["client"].get(f"/v1/tool-invocations/{queried['id']}", headers=v["headers"])
    assert rejected.status_code == 502 and "snippet_hash" not in rejected.text, rejected.text
    with session_scope() as session: session.get(ToolInvocationRecord, queried["id"]).result_payload = queried["result"]
    original_read = service.artifacts.read
    monkeypatch.setattr(service.artifacts, "read", lambda *a, **k: {"schema": "corrupt"})
    rejected = v["client"].get(url, headers=v["headers"])
    assert rejected.status_code == 502 and rejected.headers["cache-control"] == "private, no-store", rejected.text
    monkeypatch.setattr(service.artifacts, "read", original_read)
    granted = v["client"].put(f"/v1/projects/{v['project_id']}/members/{v['member']['id']}", headers=v["headers"], json={"role": "qa_lead"})
    assert granted.status_code == 200 and v["client"].get(url, headers=v["member_headers"]).status_code == 200
    restrict_source(v)
    monkeypatch.setattr(service.artifacts, "read", lambda *a, **k: pytest.fail("ACL must precede private locator bytes"))
    denied = v["client"].get(url, headers=v["member_headers"])
    assert denied.status_code == 403 and denied.headers["cache-control"] == "private, no-store", denied.text
    assert len(calls) == 2 and len(v["script_calls"]) == 1
