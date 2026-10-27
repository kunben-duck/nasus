"""Additional assertions on the real canonical recipe chain, never target calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import func, inspect, select, text, update

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.http_fixture_grants import HttpFixtureGrantRequest
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureScope
from apps.api.app.domain.quality_loop.http_fixture_grant import GRANT_TOOL, GRANT_QUERY_TOOL, GRANT_EVENT, GRANT_EVENT_FIELDS, GRANT_SECONDS
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.http_fixture_grant_models import HttpFixtureGrantRecord as Record
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.main import app
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, confirm, count


def verify_independent_operation_consent(v, metadata, monkeypatch):
    service = app.state.container.http_fixture_grants
    original_issue, errors = service.issue, []
    def diagnosed(*args, **kwargs):
        try:
            return original_issue(*args, **kwargs)
        except Exception as exc:
            errors.append((type(exc).__name__, str(exc)))
            raise
    monkeypatch.setattr(service, "issue", diagnosed)
    request = {"project_id": v["project_id"], "recipe_id": metadata["record_id"],
        "recipe_artifact_hash": metadata["artifact_hash"], "attempt_id": "attempt-" + uuid4().hex,
        "operation": "setup", "timeout_ms": 30000}
    pending = invoke(v, GRANT_TOOL, request, key=uuid4().hex)
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    assert count(v, Record) == 0
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(ValueError): service.issue(HttpFixtureGrantRequest.model_validate(request), invocation_id=pending.json()["id"])
    assert count(v, Record) == 0
    # A late failure must roll back grant, audit and Outbox together.
    append, faults = EventOutboxRepository.append, []
    def fault(repo, event, **kwargs):
        result = append(repo, event, **kwargs)
        if event.event_type == GRANT_EVENT:
            session = kwargs["session"]
            session.flush()
            assert session.get(Record, event.entity_id) is not None
            assert session.scalar(select(AuditEventRecord).where(AuditEventRecord.entity_id == event.entity_id)) is not None
            assert session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_id == event.event_id)) is not None
            faults.append(event.entity_id)
            raise RuntimeError("explicit post-Outbox consent fault")
        return result
    monkeypatch.setattr(EventOutboxRepository, "append", fault)
    result = confirm(v, pending.json())
    assert result.status_code == 200 and result.json()["status"] == "failed", (result.text, errors)
    assert len(faults) == 1 and count(v, Record) == 0
    with session_scope() as session:
        assert session.scalar(select(AuditEventRecord).where(AuditEventRecord.entity_id == faults[0])) is None
        assert session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == faults[0])) is None
    monkeypatch.setattr(EventOutboxRepository, "append", append)
    expired = invoke(v, GRANT_TOOL, request, key=uuid4().hex).json()
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, expired["id"])
        session.execute(update(ToolInvocationRecord).where(ToolInvocationRecord.id == row.id).values(status="running",
            input_payload={**row.input_payload, "confirmed_by_user": True, "confirmed_actor_id": v["owner"]["id"],
                "confirmed_at": (datetime.now(timezone.utc) - timedelta(seconds=GRANT_SECONDS + 1)).isoformat()}))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(ValueError): service.issue(HttpFixtureGrantRequest.model_validate(request), invocation_id=expired["id"])
    assert count(v, Record) == 0
    confirmed = confirm(v, invoke(v, GRANT_TOOL, request, key=uuid4().hex).json())
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "completed", (confirmed.text, errors)
    granted = completed(confirmed)
    receipt = granted["result"]["http_fixture_grant"]
    value = receipt["metadata"]
    assert value["operation"] == "setup" and value["scope_permission_recorded"] is True
    assert value["execution_authorized"] is value["fixtures_verified"] is value["business_coverage_verified"] is False
    assert datetime.fromisoformat(value["expires_at"]) - datetime.fromisoformat(value["recorded_at"]) == timedelta(seconds=GRANT_SECONDS)
    assert count(v, Record) == 1
    scope = HttpFixtureScope(**value["scope"])
    with session_scope() as session:
        now = session.scalar(select(func.clock_timestamp()))
        assert datetime.fromisoformat(value["recorded_at"]) <= now < datetime.fromisoformat(value["expires_at"])
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert service.require_operation(v["project_id"], value["record_id"], scope, "setup") == value
        with pytest.raises(PermissionError): service.require_operation(v["project_id"], value["record_id"], scope, "cleanup")
        assert service.issue(HttpFixtureGrantRequest.model_validate(request), invocation_id=granted["id"]) == value
    # Move only this repository's SQL clock expression, never immutable facts or
    # the developer DB clock. This is expiry-branch proof, not a 15-minute wait.
    clock = service.repository._clock
    monkeypatch.setattr(service.repository, "_clock", lambda: func.clock_timestamp() + text("INTERVAL '901 seconds'"))
    with pytest.raises(PermissionError):
        service.repository.require_live(v["project_id"], value["record_id"], actor_id=value["actor_id"], scope=scope,
            operation="setup", source_scope_digest=value["source_scope_digest"])
    monkeypatch.setattr(service.repository, "_clock", clock)
    rebound = confirm(v, invoke(v, GRANT_TOOL, {**request, "timeout_ms": 1000}, key=uuid4().hex).json())
    assert rebound.status_code == 200 and rebound.json()["status"] == "failed" and count(v, Record) == 1, rebound.text
    cleanup = completed(confirm(v, invoke(v, GRANT_TOOL, {**request, "operation": "cleanup"}, key=uuid4().hex).json()))
    cleanup_value = cleanup["result"]["http_fixture_grant"]["metadata"]
    assert cleanup_value["scope_digest"] == value["scope_digest"] and cleanup_value["record_id"] != value["record_id"]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert service.require_operation(v["project_id"], cleanup_value["record_id"], scope, "cleanup") == cleanup_value
        events = EventOutboxRepository().list_after(stream_kind="conversation", stream_id=v["conversation"].json()["id"],
            after_event_id=None, limit=500)
    facts = [event for event in events if event.event_type == GRANT_EVENT]
    assert len(facts) == 2
    assert all(set(event.patch) == set(GRANT_EVENT_FIELDS) and "inventory_hash" not in str(event) for event in facts)
    for event in (item for item in events if item.entity_id in {granted["id"], cleanup["id"]}):
        assert event.payload["tool_invocation"]["result"] is None and event.payload["tool_invocation"]["input_payload"] == {}
    url = f"/v1/projects/{v['project_id']}/quality/http-fixture-grants/{value['record_id']}"
    history = v["client"].get(url, headers=v["headers"])
    assert history.status_code == 200 and history.headers["cache-control"] == "private, no-store" and history.json() == receipt
    from apps.api.tests.fixture_parent_read_probe import measure_fixture_parent_reuse
    measure_fixture_parent_reuse(v, url, receipt, monkeypatch)
    # This member is qa_lead, which can read definitions but cannot approve operations.
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 403
    queried = completed(invoke(v, GRANT_QUERY_TOOL, {"project_id": v["project_id"], "record_id": value["record_id"]}))
    assert queried["result"]["http_fixture_grant"] == receipt
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(queried["id"], v["project_id"]) == receipt
    damaged = deepcopy(queried["result"])
    damaged["http_fixture_grant"]["metadata"]["scope_permission_recorded"] = 1
    with session_scope() as session:
        session.execute(update(ToolInvocationRecord).where(ToolInvocationRecord.id == queried["id"]).values(result_payload=damaged))
    assert v["client"].get(f"/v1/tool-invocations/{queried['id']}", headers=v["headers"]).status_code == 502
    with session_scope() as session:
        session.execute(update(ToolInvocationRecord).where(ToolInvocationRecord.id == queried["id"]).values(result_payload=queried["result"]))
    # The historical integrity checks may outlive the original permission; they
    # must still reject corrupted completed receipts before checking its TTL.
    origin_corrupt = deepcopy(granted["result"])
    origin_corrupt["http_fixture_grant"]["metadata"]["scope_permission_recorded"] = 1
    with session_scope() as session:
        session.execute(update(ToolInvocationRecord).where(ToolInvocationRecord.id == granted["id"]).values(result_payload=origin_corrupt))
    assert v["client"].get(url, headers=v["headers"]).status_code == 502
    with pytest.raises(ValueError):
        service.repository.require_live(v["project_id"], value["record_id"], actor_id=value["actor_id"], scope=scope,
            operation="setup", source_scope_digest=value["source_scope_digest"])
    with session_scope() as session:
        session.execute(update(ToolInvocationRecord).where(ToolInvocationRecord.id == granted["id"]).values(result_payload=granted["result"]))
    with engine.connect() as connection:
        actual = {(tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]))
            for fk in inspect(connection).get_foreign_keys(Record.__tablename__)}
        expected = {(tuple(item.parent.name for item in fk.elements), next(iter(fk.elements)).column.table.name,
            tuple(item.column.name for item in fk.elements)) for fk in Record.__table__.foreign_key_constraints}
        assert actual == expected
    for sql in ("UPDATE quality_http_fixture_grants SET status='issued' WHERE record_id=:id",
            "DELETE FROM quality_http_fixture_grants WHERE record_id=:id"):
        with engine.connect() as connection:
            transaction = connection.begin()
            with pytest.raises(Exception): connection.execute(text(sql), {"id": value["record_id"]})
            transaction.rollback()
    migration = importlib.import_module("apps.api.migrations.versions.0111_http_fixture_grants")
    with engine.connect() as connection:
        transaction = connection.begin()
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="Cannot discard"): migration.downgrade()
        transaction.rollback()
    assert count(v, Record) == 2
