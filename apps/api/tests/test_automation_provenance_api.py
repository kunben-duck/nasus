"""Real PG/private MinIO ancestry; native model HTTP is an explicit specimen."""
from copy import deepcopy
import importlib
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import delete, insert, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.application.quality_loop.test_design_results import TestDesignResultIntegrityError
from apps.api.app.application.platform.tool_models import EventPayload
from apps.api.app.infrastructure.persistence.automation_provenance_models import AutomationProvenanceRecord as Node, AutomationProvenanceEdgeRecord as Edge
from apps.api.app.infrastructure.persistence.automation_provenance_v1 import AutomationProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.automation_script_models import AutomationScriptRevisionRecord as Script
from apps.api.app.infrastructure.persistence.automation_script_review_models import AutomationScriptReviewRecord as Review
from apps.api.app.infrastructure.persistence.derivation_registry_models import DerivationRegistryRecord as DesignNode
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_automation_scripts_api import (
    native_scripts, run_confirmed, read_draft, script_review_request, independent_reviewer,
    submit_script_review, read_script_review, seed_internal_command, execute_internal,
    base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping,
)
from apps.api.tests.test_semantic_evaluations_api import completed, count
from apps.api.tests.migration_rehearsal import detach_downstream_foreign_keys, foreign_key_inventory


def values(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class RollbackProbe(Exception):
    pass


def test_native_script_review_withdrawal_and_explicit_backfill_preserve_original_derivations(native_scripts, monkeypatch):
    v = native_scripts
    _, response = run_confirmed(v)
    command = completed(response)
    read = read_draft(v, command)
    assert read.status_code == 200, read.text
    draft = read.json()
    project, script_id = v["project_id"], draft["metadata"]["script_revision_id"]
    with session_scope() as session:
        anchor = AutomationProvenanceProjectorV1().verify(session, session.get(Script, script_id))
        before = {row.node_key: values(row) for row in session.scalars(select(DesignNode).where(DesignNode.project_id == project))}
        prepared = draft["result"]["prepared"]
        expected_keys = {"context:" + prepared["context_pin"]["context_id"],
            "scope:" + prepared["scope_pin"]["revision_id"],
            "generation:" + prepared["generation_pin"]["generation_id"],
            "coverage:" + prepared["generation_pin"]["generation_id"],
            "mapping:" + prepared["mapping_pin"]["revision_id"],
            *("case:" + prepared["generation_pin"]["generation_id"] + "/" + ident for ident in prepared["selected_case_ids"])}
        assert {pin[0] for pin in anchor.parents} == expected_keys
        assert all(pin[2] == before[pin[0]]["content_hash"] for pin in anchor.parents)
        assert not {"raw_output", "artifact_ref", "oracle", "api_key"} & anchor.payload_v1.keys()
    reviewer = independent_reviewer(v)
    request = script_review_request(v, draft)
    accepted = completed(submit_script_review(reviewer, request))
    review_id = accepted["result"]["object_refs"][0].split(":", 1)[1]
    initial = read_script_review(v, review_id)
    assert initial.status_code == 200, initial.text
    original_review = initial.json()
    withdrawn = completed(submit_script_review(reviewer, {**request, "expected_previous_revision_id": review_id,
        "decision": "withdraw", "actions": None, "assertions": None, "reason": "Independent protocol withdrawal"}))
    withdrawn_id = withdrawn["result"]["object_refs"][0].split(":", 1)[1]
    with session_scope() as session:
        rows = session.scalars(select(Review).where(Review.project_id == project).order_by(Review.sequence)).all()
        registered = AutomationProvenanceProjectorV1().reviews(session, session.get(Script, script_id), rows)
        assert len(registered) == 2 and registered[0].artifact_id == review_id and registered[1].artifact_id == withdrawn_id
        assert registered[0].parents == ((anchor.key, anchor.artifact_hash, anchor.content_hash),)
        assert set(registered[1].parents) == {(anchor.key, anchor.artifact_hash, anchor.content_hash),
            (registered[0].key, registered[0].artifact_hash, registered[0].content_hash)}
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_type.in_(
            ("quality.automation.draft_saved", "quality.automation.script_reviewed")),
            SSEEventOutboxRecord.event_payload["correlation_id"].as_string() == project).order_by(SSEEventOutboxRecord.sequence)).all()
        frozen_events = [deepcopy(row.event_payload) for row in events]
        assert len(frozen_events) == 3
        for event in frozen_events:
            AutomationProvenanceProjectorV1().project_event(session, EventPayload.model_validate(event))
        node_values = {row.node_key: values(row) for row in session.scalars(select(Node).where(Node.project_id == project))}
        edge_values = [values(row) for row in session.scalars(select(Edge).where(Edge.project_id == project))]
    assert count(v, Node) == 3 and count(v, Edge) == len(anchor.parents) + 3
    assert read_draft(v, command).json() == draft and len(v["script_calls"]) == 1
    history = read_script_review(v, review_id).json()
    assert history["request"] == original_review["request"] and history["script_pin"] == original_review["script_pin"]
    assert history["current_use"]["review_current"] is False and history["current_use"]["execution_authorized"] is False
    for statement in (update(Node).where(Node.project_id == project).values(content_hash="changed"),
            delete(Edge).where(Edge.project_id == project)):
        with pytest.raises(IntegrityError), session_scope() as session:
            session.execute(statement)
    # Fault injection occurs only in this disposable database. Normal reads and
    # Outbox replay must not recreate even one missing historical edge.
    removed = next(edge for edge in edge_values if edge["node_key"] == anchor.key)
    for changes in ({"parent_hash": "sha256:" + "0" * 64}, {"context_id": "foreign-context"},
            {"automation_key": removed["parent_key"], "test_design_key": None}):
        with pytest.raises(IntegrityError), session_scope() as session:
            session.execute(text("ALTER TABLE quality_automation_provenance_edges DISABLE TRIGGER USER"))
            session.execute(delete(Edge).where(Edge.project_id == project, Edge.node_key == removed["node_key"],
                Edge.parent_key == removed["parent_key"]))
            session.execute(insert(Edge).values({**removed, **changes}))
    with session_scope() as session:
        session.execute(text("ALTER TABLE quality_automation_provenance_edges DISABLE TRIGGER USER"))
        session.execute(delete(Edge).where(Edge.project_id == project, Edge.node_key == removed["node_key"],
            Edge.parent_key == removed["parent_key"]))
        session.execute(text("ALTER TABLE quality_automation_provenance_edges ENABLE TRIGGER USER"))
    try:
        failed = read_draft(v, command)
        assert failed.status_code == 502 and "result" not in failed.json()
        with pytest.raises(TestDesignResultIntegrityError), session_scope() as session:
            AutomationProvenanceProjectorV1().project_event(session, EventPayload.model_validate(frozen_events[0]))
        with pytest.raises(TestDesignResultIntegrityError):
            EventOutboxRepository().append(EventPayload.model_validate({**frozen_events[0], "event_id": str(uuid4())}))
        assert count(v, Edge) == len(edge_values) - 1 and len(v["script_calls"]) == 1
    finally:
        with session_scope() as session:
            session.execute(insert(Edge).values(removed))
    assert read_draft(v, command).status_code == 200
    # Explicit metadata migration can reconstruct the exact historical ledger;
    # it cannot read a new model, current head, workspace file or object body.
    with session_scope() as session:
        session.execute(text("ALTER TABLE quality_automation_provenance_edges DISABLE TRIGGER USER"))
        session.execute(delete(Edge).where(Edge.project_id == project))
        session.execute(text("ALTER TABLE quality_automation_provenance_edges ENABLE TRIGGER USER"))
        session.execute(text("ALTER TABLE quality_automation_provenance DISABLE TRIGGER USER"))
        session.execute(delete(Node).where(Node.project_id == project))
        session.execute(text("ALTER TABLE quality_automation_provenance ENABLE TRIGGER USER"))
    assert read_draft(v, command).status_code == 502
    with session_scope() as session:
        assert AutomationProvenanceProjectorV1().backfill(session) >= 3
        after = {row.node_key: values(row) for row in session.scalars(select(DesignNode).where(DesignNode.project_id == project))}
        assert after == before
        assert {row.node_key: values(row) for row in session.scalars(select(Node).where(Node.project_id == project))} == node_values
        assert AutomationProvenanceProjectorV1().backfill(session) >= 3
    assert read_draft(v, command).json() == draft and len(v["script_calls"]) == 1
    migration = importlib.import_module("apps.api.migrations.versions.0100_automation_provenance")
    with session_scope() as session:
        monkeypatch.setattr(migration, "op", type("MigrationOp", (), {"get_bind": staticmethod(lambda: session.connection())}))
        with pytest.raises(RuntimeError, match="Cannot discard"):
            migration.downgrade()
    # Rehearse populated 0099 -> 0100 DDL/backfill inside a rollback-only
    # PostgreSQL transaction, not merely backfill into existing empty tables.
    with engine.connect() as connection:
        original_foreign_keys = foreign_key_inventory(connection)
    with pytest.raises(RollbackProbe), engine.begin() as connection:
        scoped_op = Operations(MigrationContext.configure(connection))
        detach_downstream_foreign_keys(connection, scoped_op, migration.TABLES)
        for table in reversed(migration.TABLES):
            scoped_op.drop_table(table)
        monkeypatch.setattr(migration, "op", scoped_op)
        migration.upgrade()
        inspector = inspect(connection)
        for model in (Node, Edge):
            table = model.__table__
            columns = inspector.get_columns(table.name)
            assert [column["name"] for column in columns] == list(table.columns.keys())
            for actual, expected in zip(columns, table.columns):
                assert actual["nullable"] == expected.nullable
                assert actual["type"]._type_affinity is expected.type._type_affinity
            actual_fks = {(tuple(value["constrained_columns"]), value["referred_table"], tuple(value["referred_columns"]))
                for value in inspector.get_foreign_keys(table.name)}
            expected_fks = {(tuple(value.column_keys), next(iter(value.elements)).column.table.name,
                tuple(element.column.name for element in value.elements)) for value in table.foreign_key_constraints}
            assert actual_fks == expected_fks
            assert {value["name"]: tuple(value["column_names"]) for value in inspector.get_indexes(table.name)
                if not value.get("duplicates_constraint")} == {value.name: tuple(value.columns.keys()) for value in table.indexes}
        with Session(bind=connection) as session:
            assert {row.node_key: values(row) for row in session.scalars(select(Node).where(Node.project_id == project))} == node_values
            actual_edges = [values(row) for row in session.scalars(select(Edge).where(Edge.project_id == project))]
            assert sorted(actual_edges, key=lambda value: (value["node_key"], value["parent_key"])) == sorted(
                edge_values, key=lambda value: (value["node_key"], value["parent_key"]))
            assert {row.node_key: values(row) for row in session.scalars(select(DesignNode).where(DesignNode.project_id == project))} == before
        with pytest.raises(RuntimeError, match="Cannot discard"):
            migration.downgrade()
        raise RollbackProbe()
    with engine.connect() as connection:
        assert foreign_key_inventory(connection) == original_foreign_keys
    assert read_draft(v, command).json() == draft
    with pytest.raises(TestDesignResultIntegrityError), engine.begin() as connection:
        scoped_op = Operations(MigrationContext.configure(connection))
        detach_downstream_foreign_keys(connection, scoped_op, migration.TABLES)
        for table in reversed(migration.TABLES):
            scoped_op.drop_table(table)
        monkeypatch.setattr(migration, "op", scoped_op)
        connection.execute(text("ALTER TABLE quality_automation_script_revisions DISABLE TRIGGER USER"))
        connection.execute(update(Script).where(Script.script_revision_id == script_id)
            .values(content_hash="sha256:" + "0" * 64))
        migration.upgrade()
    with engine.connect() as connection:
        assert foreign_key_inventory(connection) == original_foreign_keys
    assert read_draft(v, command).json() == draft and len(v["script_calls"]) == 1


def test_provenance_failure_rolls_back_script_review_audit_and_outbox_without_resending_native_reply(native_scripts, monkeypatch):
    v = native_scripts
    ident = seed_internal_command(v)
    original = AutomationProvenanceProjectorV1.record_script

    def fail_script(self, session, row):
        original(self, session, row)
        raise TestDesignResultIntegrityError("injected provenance transaction failure")

    monkeypatch.setattr(AutomationProvenanceProjectorV1, "record_script", fail_script)
    with pytest.raises(TestDesignResultIntegrityError, match="injected"):
        execute_internal(v, ident)
    assert count(v, Script) == count(v, Node) == count(v, Edge) == 0
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.entity_id == ident,
            AuditEventRecord.action == "quality.automation.draft_saved")).all()
        assert not session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == ident,
            SSEEventOutboxRecord.event_type == "quality.automation.draft_saved")).all()
    monkeypatch.setattr(AutomationProvenanceProjectorV1, "record_script", original)
    metadata = execute_internal(v, ident)
    assert execute_internal(v, ident) == metadata and len(v["script_calls"]) == 1
    url = f"/v1/projects/{v['project_id']}/quality/automation-script-revisions/{metadata['script_revision_id']}"
    draft = v["client"].get(url, headers=v["headers"])
    assert draft.status_code == 200, draft.text
    reviewer = independent_reviewer(v)
    request = script_review_request(v, draft.json())
    original_review = AutomationProvenanceProjectorV1.record_review

    def fail_review(self, session, row):
        original_review(self, session, row)
        raise TestDesignResultIntegrityError("injected review provenance transaction failure")

    monkeypatch.setattr(AutomationProvenanceProjectorV1, "record_review", fail_review)
    response = submit_script_review(reviewer, request)
    assert response.json()["status"] == "failed", response.text
    assert count(v, Review) == 0 and count(v, Node) == 1
    with session_scope() as session:
        assert not session.scalars(select(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_type == "quality.automation.script_reviewed",
            SSEEventOutboxRecord.event_payload["correlation_id"].as_string() == v["project_id"])).all()
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.action == "quality.automation.script_reviewed",
            AuditEventRecord.conversation_id == reviewer["conversation"].json()["id"])).all()
    monkeypatch.setattr(AutomationProvenanceProjectorV1, "record_review", original_review)
    completed(submit_script_review(reviewer, request))
    assert count(v, Review) == 1 and count(v, Node) == 2 and len(v["script_calls"]) == 1
