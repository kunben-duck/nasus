"""Real canonical PG/private MinIO chain; no Runner or business-oracle approval."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import inspect, select, text, update

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.http_fixture_recipes import HttpFixtureRecipeRequest
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixture_recipe import (
    RECIPE_TOOL, RECIPE_QUERY_TOOL, RECIPE_EVENT, RECIPE_EVENT_FIELDS, RECIPE_FALSE_AUTHORITIES, RECIPE_ZERO_COUNTS,
)
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.http_fixture_recipe_models import HttpFixtureRecipeRecord as Record
from apps.api.app.infrastructure.persistence.http_fixture_journal_models import HttpFixtureDispatchRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_http_fixtures import manifest
from apps.api.tests.test_run_plans_api import (
    base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping, native_scripts,
    select_binding_scripts, reviewed_plan_inputs, preview, submit, read,
)
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, confirm, count
from apps.api.tests.test_source_access_api import grant_member, policy as restrict_source


def test_confirmed_recipe_original_runplan_atomic_history_and_source_acl(native_scripts, monkeypatch):
    v = native_scripts
    select_binding_scripts(v)
    _, _, _, selection = reviewed_plan_inputs(v)
    inputs = selection.model_dump(mode="json")
    declaration = inputs["fixtures"][0]
    recipe = {**manifest(), **{key: declaration[key] for key in ("case_id", "preconditions_digest", "setup", "cleanup")}}
    recipe["setup_steps"][-1]["value_json"] = '"EXPLICIT_INDEPENDENT_EXPECTED"'
    declaration["data_manifest_hash"] = acceptance_digest(recipe)
    # New protocol-only plan declaration; no target starts and no saved plan is
    # rewritten. Operation consent is limited to the owned inspector's endpoint.
    inputs["environment"]["base_url"] = "http://127.0.0.1:8080"
    inputs["policy_revision"] = "nasus.run-plan.v2"
    selection = type(selection).model_validate(inputs)
    saved_plan = completed(submit(v, preview(v, selection).json()["request"]))
    plan_id = saved_plan["result"]["object_refs"][0].split(":", 1)[1]
    plan = read(v, plan_id).json()
    assert plan["artifact"]["plan"]["selection"]["environment"]["base_url"] == "http://127.0.0.1:8080"
    request = {"project_id": v["project_id"], "run_plan_id": plan_id,
        "run_plan_artifact_hash": plan["metadata"]["artifact_hash"], "manifest": recipe}
    service = app.state.container.http_fixture_recipes
    original_record, errors = service.record, []
    def diagnosed(*args, **kwargs):
        try: return original_record(*args, **kwargs)
        except Exception as exc:
            errors.append((type(exc).__name__, str(exc)))
            raise
    monkeypatch.setattr(service, "record", diagnosed)
    original_put, writes = service.artifacts.put, []
    def put(*args, **kwargs):
        writes.append("private recipe")
        return original_put(*args, **kwargs)
    monkeypatch.setattr(service.artifacts, "put", put)
    pending = invoke(v, RECIPE_TOOL, request, key=uuid4().hex)
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    assert count(v, Record) == 0 and not writes and count(v, HttpFixtureDispatchRecord) == 0
    with session_scope() as session:
        command = session.get(ToolInvocationRecord, pending.json()["id"])
        data = {**command.input_payload, "confirmed_by_user": True, "confirmed_actor_id": v["owner"]["id"],
            "confirmed_at": (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()}
        session.execute(update(ToolInvocationRecord).where(ToolInvocationRecord.id == command.id).values(input_payload=data, status="running"))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(ValueError): service.record(HttpFixtureRecipeRequest.model_validate(request),
            invocation_id=pending.json()["id"], recorded_at=datetime.now(timezone.utc).isoformat())
    assert count(v, Record) == 0 and not writes
    append, faults = EventOutboxRepository.append, []
    def late_fault(repository, event, **kwargs):
        result = append(repository, event, **kwargs)
        if event.event_type == RECIPE_EVENT:
            session = kwargs["session"]
            session.flush()
            assert session.get(Record, event.entity_id) is not None
            assert session.scalar(select(AuditEventRecord).where(AuditEventRecord.entity_id == event.entity_id)) is not None
            assert session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_id == event.event_id)) is not None
            faults.append(event.entity_id)
            raise RuntimeError("explicit post-Outbox recipe transaction fault")
        return result
    monkeypatch.setattr(EventOutboxRepository, "append", late_fault)
    failed = confirm(v, invoke(v, RECIPE_TOOL, request, key=uuid4().hex).json())
    assert failed.status_code == 200 and failed.json()["status"] == "failed", failed.text
    assert len(faults) == 1 and count(v, Record) == 0, errors
    with session_scope() as session:
        assert session.scalar(select(AuditEventRecord).where(AuditEventRecord.entity_id == faults[0])) is None
        assert session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == faults[0])) is None
    monkeypatch.setattr(EventOutboxRepository, "append", append)
    pending = invoke(v, RECIPE_TOOL, request, key=uuid4().hex)
    registered = completed(confirm(v, pending.json()))
    receipt = registered["result"]["http_fixture_recipe"]
    metadata, record_id = receipt["metadata"], receipt["metadata"]["record_id"]
    assert all(metadata[key] is False for key in RECIPE_FALSE_AUTHORITIES)
    assert all(type(metadata[key]) is int and metadata[key] == 0 for key in RECIPE_ZERO_COUNTS)
    assert metadata["data_manifest_hash"] == declaration["data_manifest_hash"]
    assert metadata["recipe_bytes_verified"] is True
    assert count(v, Record) == 1 and count(v, HttpFixtureDispatchRecord) == 0
    assert len(writes) == 2 and "value_json" not in str(registered["result"]) and "setup_steps" not in str(registered["result"])
    assert registered["input_payload"]["manifest"] == recipe
    with session_scope() as session:
        row = session.get(Record, record_id)
        assert row.artifact_ref.startswith("s3://")
        original_ref = row.artifact_ref
    url = f"/v1/projects/{v['project_id']}/quality/http-fixture-recipes/{record_id}"
    view = v["client"].get(url, headers=v["headers"])
    assert view.status_code == 200 and view.headers["cache-control"] == "private, no-store", view.text
    assert view.json()["archive"]["request"]["manifest"] == recipe and view.json()["metadata"] == metadata
    assert "EXPLICIT_INDEPENDENT_EXPECTED" in view.text
    queried = completed(invoke(v, RECIPE_QUERY_TOOL, {"project_id": v["project_id"], "record_id": record_id}))
    assert queried["result"]["http_fixture_recipe"] == receipt
    from apps.api.tests.http_fixture_grant_pg_checks import verify_independent_operation_consent
    verify_independent_operation_consent(v, metadata, monkeypatch)
    monkeypatch.setattr(service.artifacts, "put", lambda *a, **k: pytest.fail("history created new recipe"))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert service.record(HttpFixtureRecipeRequest.model_validate(request), invocation_id=registered["id"], recorded_at="ignored") == metadata
        assert app.state.container.tool_evidence.describe(queried["id"], v["project_id"]) == receipt
        events = EventOutboxRepository().list_after(stream_kind="conversation", stream_id=v["conversation"].json()["id"],
            after_event_id=None, limit=500)
    facts = [event for event in events if event.event_type == RECIPE_EVENT]
    assert len(facts) == 1 and facts[0].patch == {key: metadata[key] for key in RECIPE_EVENT_FIELDS}
    assert "setup_steps" not in str(facts[0]) and "EXPLICIT_INDEPENDENT_EXPECTED" not in str(facts[0])
    for event in (event for event in events if event.entity_id in {registered["id"], queried["id"]}):
        assert event.payload["tool_invocation"]["result"] is None and event.payload["tool_invocation"]["input_payload"] == {}
    with engine.connect() as connection:
        actual = {(tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"]))
            for item in inspect(connection).get_foreign_keys(Record.__tablename__)}
        expected = {(tuple(element.parent.name for element in constraint.elements), next(iter(constraint.elements)).column.table.name,
            tuple(element.column.name for element in constraint.elements)) for constraint in Record.__table__.foreign_key_constraints}
        assert actual == expected
    for sql in ("UPDATE quality_http_fixture_recipes SET status='recorded' WHERE record_id=:id",
            "DELETE FROM quality_http_fixture_recipes WHERE record_id=:id"):
        with engine.connect() as connection:
            transaction = connection.begin()
            with pytest.raises(Exception): connection.execute(text(sql), {"id": record_id})
            transaction.rollback()
    migration = importlib.import_module("apps.api.migrations.versions.0110_http_fixture_recipes")
    with engine.connect() as connection:
        transaction = connection.begin()
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="Cannot discard"): migration.downgrade()
        transaction.rollback()
    damaged = deepcopy(queried["result"])
    damaged["http_fixture_recipe"]["metadata"]["recipe_bytes_verified"] = 1
    with session_scope() as session:
        session.execute(update(ToolInvocationRecord).where(ToolInvocationRecord.id == queried["id"]).values(result_payload=damaged))
    with session_scope() as session:
        stored = session.get(ToolInvocationRecord, queried["id"]).result_payload
        assert type(stored["http_fixture_recipe"]["metadata"]["recipe_bytes_verified"]) is int
    rejected = v["client"].get(f"/v1/tool-invocations/{queried['id']}", headers=v["headers"])
    assert rejected.status_code == 502, rejected.text
    with session_scope() as session:
        session.execute(update(ToolInvocationRecord).where(ToolInvocationRecord.id == queried["id"]).values(result_payload=queried["result"]))
    with session_scope() as session:
        restored_result = session.get(ToolInvocationRecord, queried["id"]).result_payload
        assert type(restored_result["http_fixture_recipe"]["metadata"]["recipe_bytes_verified"]) is bool
    original_read = service.artifacts.read
    monkeypatch.setattr(service.artifacts, "read", lambda *a, **k: {"schema": "corrupt"})
    rejected = v["client"].get(url, headers=v["headers"])
    assert rejected.status_code == 502 and rejected.headers["cache-control"] == "private, no-store", rejected.text
    monkeypatch.setattr(service.artifacts, "read", original_read)
    # Physically remove only this test recipe, then restore its exact original bytes.
    storage = service.artifacts.storage
    assert storage.config.bucket.startswith("nasus-test-")
    body = storage.get_bytes(original_ref, max_bytes=service.artifacts.MAX_BYTES)
    key = service.artifacts._key(v["project_id"], metadata["artifact_hash"])
    with storage._s3_write_client() as client:
        client.delete_object(Bucket=storage.config.bucket, Key=key)
    rejected = v["client"].get(url, headers=v["headers"])
    assert rejected.status_code == 503 and rejected.headers["cache-control"] == "private, no-store", rejected.text
    restored = storage.put_bytes(key, body, content_type="application/json")
    assert restored.storage_ref == original_ref and restored.content_hash == metadata["artifact_hash"]
    assert v["client"].get(url, headers=v["headers"]).status_code == 200
    # The original script-review fixture promoted this member to qa_lead.
    grant_member(v)
    with actor_scope(UserProfile.model_validate(v["member"])):
        assert service.authorization.scope(v["project_id"]).effective_project_role == "viewer"
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 403
    granted = v["client"].put(f"/v1/projects/{v['project_id']}/members/{v['member']['id']}", headers=v["headers"], json={"role": "qa_lead"})
    assert granted.status_code == 200 and v["client"].get(url, headers=v["member_headers"]).status_code == 200
    restrict_source(v)
    monkeypatch.setattr(service.artifacts, "read", lambda *a, **k: pytest.fail("ACL must precede private recipe bytes"))
    denied = v["client"].get(url, headers=v["member_headers"])
    assert denied.status_code == 403 and denied.headers["cache-control"] == "private, no-store", denied.text
    assert count(v, Record) == 1 and count(v, HttpFixtureDispatchRecord) == 0 and len(v["script_calls"]) == 1


def test_fixed_exweb_fixture_operation_consent_preserves_all_source_pins(native_scripts, monkeypatch):
    """Actual fixed source/PG/MinIO; transport/oracles remain explicit specimens."""
    from apps.api.tests.test_automation_input_api import verify_fixed_exweb_archive
    from apps.api.app.infrastructure.persistence.http_fixture_grant_models import HttpFixtureGrantRecord
    v = native_scripts
    assert v["exweb_commit"] == "fe5827f6b76f77ef34918d8b452ee823142332dc" and v["exweb_file_count"] == 126
    test_confirmed_recipe_original_runplan_atomic_history_and_source_acl(v, monkeypatch)
    source_pin, member_count = verify_fixed_exweb_archive(v, v["script_sent"][0])
    assert source_pin["file_count"] == 126 and member_count > 0
    assert count(v, HttpFixtureGrantRecord) == 2 and count(v, HttpFixtureDispatchRecord) == 0
