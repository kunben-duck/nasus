"""Native authority commands, fixed source graphs and rollback in disposable PG."""
import importlib
import json

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import delete, insert, inspect as inspect_database, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.domain.quality_loop.acceptance_specification import AcceptanceIntegrityError
from apps.api.app.domain.system_image.context_partition import RULE_AUTHORITY_POLICY
from apps.api.app.infrastructure.persistence.authority_provenance_models import AuthorityProvenanceRecord as Anchor
from apps.api.app.infrastructure.persistence.authority_provenance_projection_v1 import AuthorityProvenanceProjectorV1 as Projector
from apps.api.app.infrastructure.persistence.acceptance_specification_models import AcceptanceRevisionRecord
from apps.api.app.infrastructure.persistence.business_rule_models import BusinessRuleRevisionRecord
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord as Event
from apps.api.app.infrastructure.persistence.object_provenance_models import ObjectProvenanceNodeRecord as ObjectNode
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_acceptance_specifications_api import acceptance, documents, evidence_api, submit, inspect
from apps.api.tests.test_business_rules_api import rule, submit_rule, inspect_rule
from apps.api.tests.test_semantic_evaluations_api import completed, count
from apps.api.tests.test_context_packs_api import preview, archive, read
from apps.api.tests.test_relation_provenance_api import RollbackProbe


@pytest.fixture(params=["acceptance", "business_rule"])
def authority(request):
    kind = request.param
    v = request.getfixturevalue("acceptance" if kind == "acceptance" else "rule")
    v.update(authority_kind=kind,
        authority_submit=submit if kind == "acceptance" else submit_rule,
        authority_inspect=inspect if kind == "acceptance" else inspect_rule,
        authority_model=AcceptanceRevisionRecord if kind == "acceptance" else BusinessRuleRevisionRecord,
        authority_request=v["ac_request"] if kind == "acceptance" else v["rule_request"],
        authority_url=v["ac_url"] if kind == "acceptance" else v["rule_url"])
    return v


def anchors(session, project):
    return [dict(row) for row in session.execute(select(*Anchor.__table__.columns).where(
        Anchor.project_id == project).order_by(Anchor.kind, Anchor.sequence)).mappings()]


def withdraw(v, head):
    return v["authority_submit"](v, {**v["authority_request"], "decision": "withdraw", "oracle": None,
        "authority_basis": None, "expected_previous_revision_id": head["revision_id"], "reason": "Withdraw fixture oracle"})


def test_authority_inspection_verifies_one_source_once_and_never_reuses_it_across_requests(authority, monkeypatch):
    v = authority
    completed(v["authority_submit"](v))
    service = v["ac_service"] if v["authority_kind"] == "acceptance" else v["rule_service"]
    source, images = service.sources, service.sources.images
    original_source, original_metadata = source._inspect, images.repository._get
    calls, metadata_reads = [], []

    def inspect_source(*args):
        calls.append(args)
        assert images._verified_reads.get() is not None
        return original_source(*args)

    def read_metadata(*args):
        metadata_reads.append(args[1:])
        return original_metadata(*args)

    monkeypatch.setattr(source, "_inspect", inspect_source)
    monkeypatch.setattr(images.repository, "_get", read_metadata)
    first = v["authority_inspect"](v)
    assert first["head"]["status"] == "approved" and first["current"]["oracle"]
    assert len(calls) == len(metadata_reads) == 1
    assert v["authority_inspect"](v) == first
    assert len(calls) == len(metadata_reads) == 2

    original_artifact = images.artifacts.read

    def corrupt_archive(*args):
        value = original_artifact(*args)
        return {**value, "manifest_hash": "sha256:" + "0" * 64}

    monkeypatch.setattr(images.artifacts, "read", corrupt_archive)
    query = v["ac_query"] if v["authority_kind"] == "acceptance" else v["rule_query"]
    damaged = v["client"].get(v["authority_url"], params=query, headers=v["headers"])
    assert damaged.status_code == 502 and "oracle" not in damaged.json(), damaged.text
    assert len(calls) == len(metadata_reads) == 3
    monkeypatch.setattr(images.artifacts, "read", original_artifact)
    assert v["authority_inspect"](v) == first
    assert len(calls) == len(metadata_reads) == 4


def drop_later_authority_dependents(connection):
    # Rehearse 0074 inside the existing rollback-only migration fixture.
    # Its later FK-bearing graph must be removed first, never via production CASCADE.
    for table in ("system_image_context_authority_dependencies", "system_image_context_authority_backfill_targets",
                  "system_image_context_authority_roots"):
        connection.execute(text(f"DROP TABLE {table}"))
    connection.execute(text("DROP FUNCTION nasus_reject_context_authority_mutation()"))


def test_approved_withdrawn_and_reapproved_authorities_pin_native_sources_and_predecessors(authority):
    v = authority
    completed(v["authority_submit"](v))
    first = v["authority_inspect"](v)["head"]
    url = v["authority_url"] + "/" + first["revision_id"]
    original = v["client"].get(url, headers=v["headers"]).json()
    completed(withdraw(v, first))
    second = v["authority_inspect"](v)["head"]
    completed(v["authority_submit"](v, {**v["authority_request"], "expected_previous_revision_id": second["revision_id"]}))
    with session_scope() as session:
        rows = anchors(session, v["project_id"])
        assert [row["status"] for row in rows] == ["approved", "withdrawn", "approved"]
        assert [row["previous_registration_hash"] for row in rows] == [None, rows[0]["content_hash"], rows[1]["content_hash"]]
        assert all(row["kind"] == v["authority_kind"] for row in rows)
        for row in rows:
            native = session.get(v["authority_model"], row["revision_id"])
            assert row["metadata_hash"] == native.content_hash and row["artifact_hash"] == native.payload["artifact_hash"]
            for key, digest in (("image_node_key", "image_provenance_hash"), ("member_node_key", "member_provenance_hash"),
                                ("document_node_key", "document_provenance_hash")):
                assert session.get(ObjectNode, (v["project_id"], row[key])).content_hash == row[digest]
        assert Projector().backfill(session) == 0 and anchors(session, v["project_id"]) == rows
        assert len(session.scalars(select(Event).where(Event.entity_id.in_([row["revision_id"] for row in rows]))).all()) == 3
        serialized = json.dumps(rows)
        assert not any(value in serialized for value in ("HTTP 400", "HTTP 401", "local-object://", "s3://", "source_fields"))
    assert v["client"].get(url, headers=v["headers"]).json() == original


@pytest.mark.parametrize("damage", ["missing", "metadata_hash"])
def test_bad_authority_registration_blocks_reads_new_decisions_and_context_without_repair(authority, damage):
    v = authority
    completed(v["authority_submit"](v))
    head = v["authority_inspect"](v)["head"]
    url = v["authority_url"] + "/" + head["revision_id"]
    original = v["client"].get(url, headers=v["headers"]).json()
    with session_scope() as session:
        saved = anchors(session, v["project_id"])
        session.execute(text("ALTER TABLE requirement_authority_provenance DISABLE TRIGGER USER"))
        if damage == "missing":
            session.execute(delete(Anchor).where(Anchor.project_id == v["project_id"]))
        else:
            session.execute(update(Anchor).where(Anchor.project_id == v["project_id"]).values(metadata_hash="sha256:" + "0" * 64))
        session.execute(text("ALTER TABLE requirement_authority_provenance ENABLE TRIGGER USER"))
        damaged = anchors(session, v["project_id"])
        events = set(session.scalars(select(Event.event_id).where(Event.entity_id == head["revision_id"])))
    try:
        response = v["client"].get(url, headers=v["headers"])
        assert response.status_code == 502, response.text
        assert "oracle" not in response.json() and "HTTP 400" not in response.text and "HTTP 401" not in response.text
        assert v["client"].get(url).status_code == 401
        result = withdraw(v, head)
        assert result.status_code == 200 and result.json()["status"] == "failed", result.text
        context = v["client"].get(f"{v['image_url']}/context-packs/preview", headers=v["headers"],
            params={"image_revision_id": head["image_revision_id"], "image_artifact_hash": head["image_artifact_hash"],
                "policy_revision": RULE_AUTHORITY_POLICY})
        assert context.status_code == 502, context.text
        with session_scope() as session:
            assert anchors(session, v["project_id"]) == damaged
            assert count(v, v["authority_model"]) == 1
            assert set(session.scalars(select(Event.event_id).where(Event.entity_id == head["revision_id"]))) == events
    finally:
        with session_scope() as session:
            session.execute(text("ALTER TABLE requirement_authority_provenance DISABLE TRIGGER USER"))
            if damage == "missing":
                session.execute(insert(Anchor), saved)
            else:
                session.execute(update(Anchor).where(Anchor.project_id == v["project_id"]).values(metadata_hash=saved[0]["metadata_hash"]))
            session.execute(text("ALTER TABLE requirement_authority_provenance ENABLE TRIGGER USER"))
    assert v["client"].get(url, headers=v["headers"]).json() == original


@pytest.mark.parametrize("damage", ["missing_current", "bad_predecessor"])
def test_authority_event_cannot_repair_source_pins_lost_after_repository_check(authority, monkeypatch, damage):
    v = authority
    completed(v["authority_submit"](v))
    head = v["authority_inspect"](v)["head"]
    method, injected = Projector.project_event, []
    with session_scope() as session:
        before = anchors(session, v["project_id"])
    def lose_predecessor(self, session, event):
        if event.event_type == "quality." + ("acceptance_specification" if v["authority_kind"] == "acceptance" else "business_rule") + ".reviewed":
            session.execute(text("ALTER TABLE requirement_authority_provenance DISABLE TRIGGER USER"))
            if damage == "missing_current":
                session.execute(delete(Anchor).where(Anchor.project_id == v["project_id"], Anchor.revision_id == event.entity_id))
            else:
                session.execute(update(Anchor).where(Anchor.project_id == v["project_id"], Anchor.revision_id == head["revision_id"])
                    .values(metadata_hash="sha256:" + "0" * 64))
            session.execute(text("ALTER TABLE requirement_authority_provenance ENABLE TRIGGER USER"))
            injected.append(event.entity_id)
        return method(self, session, event)
    monkeypatch.setattr(Projector, "project_event", lose_predecessor)
    assert withdraw(v, head).json()["status"] == "failed"
    assert len(injected) == 1
    with session_scope() as session:
        assert anchors(session, v["project_id"]) == before and count(v, v["authority_model"]) == 1
        assert not session.scalars(select(Event).where(Event.entity_id.in_(injected))).all()
    assert v["authority_inspect"](v)["head"] == head


def test_fixed_context_keeps_original_authority_pin_but_withdrawal_invalidates_current_use(authority):
    v = authority
    completed(v["authority_submit"](v))
    head = v["authority_inspect"](v)["head"]
    before = preview(v, policy_revision=RULE_AUTHORITY_POLICY)
    response, _ = archive(v, before)
    context, url = read(v, completed(response))
    pin = next(item["authority"] for item in context["context"]["required_constraints"]
        if item["object_id"] == head["object_id"])
    assert pin["revision_id"] == head["revision_id"] and pin["artifact_hash"] == head["artifact_hash"]
    with session_scope() as session:
        original = anchors(session, v["project_id"])
    completed(withdraw(v, head))
    response = v["client"].get(url, headers=v["headers"])
    assert response.status_code == 200, response.text
    historical = response.json()
    assert historical["metadata"] == context["metadata"] and historical["context"] == context["context"]
    assert historical["current_use"]["stale"] and not historical["current_use"]["generation_authorized"]
    with session_scope() as session:
        assert anchors(session, v["project_id"])[:1] == original


def test_authority_source_pins_are_append_only_and_cross_project_foreign_keys_are_enforced(authority):
    v = authority
    completed(v["authority_submit"](v))
    with session_scope() as session:
        saved = anchors(session, v["project_id"])[0]
    for statement in (update(Anchor).where(Anchor.project_id == v["project_id"]).values(status="withdrawn"),
                      delete(Anchor).where(Anchor.project_id == v["project_id"])):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement)
    with pytest.raises(IntegrityError):
        with session_scope() as session:
            session.execute(insert(Anchor).values(**{**saved, "project_id": "foreign-project"}))


def test_populated_migration_backfills_native_history_without_changing_public_authority(authority, monkeypatch):
    v = authority
    completed(v["authority_submit"](v))
    head = v["authority_inspect"](v)["head"]
    completed(withdraw(v, head))
    original = v["authority_inspect"](v)
    with session_scope() as session:
        before = anchors(session, v["project_id"])
    migration = importlib.import_module("apps.api.migrations.versions.0074_authority_provenance")
    with pytest.raises(RollbackProbe), engine.begin() as connection:
        scoped_op = Operations(MigrationContext.configure(connection))
        drop_later_authority_dependents(connection)
        scoped_op.drop_table(migration.TABLE)
        scoped_op.execute("DROP FUNCTION nasus_reject_authority_provenance_mutation()")
        monkeypatch.setattr(migration, "op", scoped_op)
        migration.upgrade()
        with Session(bind=connection) as session:
            assert anchors(session, v["project_id"]) == before
            assert Projector().backfill(session) == 0
        with pytest.raises(RuntimeError, match="Cannot discard"):
            migration.downgrade()
        raise RollbackProbe()
    assert v["authority_inspect"](v) == original


def test_bad_native_authority_digest_aborts_migration_ddl_and_backfill(authority, monkeypatch):
    v = authority
    completed(v["authority_submit"](v))
    original = v["authority_inspect"](v)
    migration = importlib.import_module("apps.api.migrations.versions.0074_authority_provenance")
    with pytest.raises(AcceptanceIntegrityError), engine.begin() as connection:
        scoped_op = Operations(MigrationContext.configure(connection))
        drop_later_authority_dependents(connection)
        scoped_op.drop_table(migration.TABLE)
        scoped_op.execute("DROP FUNCTION nasus_reject_authority_provenance_mutation()")
        monkeypatch.setattr(migration, "op", scoped_op)
        table = v["authority_model"].__tablename__
        connection.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
        connection.execute(update(v["authority_model"]).where(v["authority_model"].project_id == v["project_id"])
            .values(content_hash="sha256:" + "0" * 64))
        migration.upgrade()
    assert v["authority_inspect"](v) == original


def test_authority_anchor_ddl_matches_types_column_order_and_nullability():
    columns = inspect_database(engine).get_columns(Anchor.__tablename__)
    assert [column["name"] for column in columns] == list(Anchor.__table__.columns.keys())
    for actual, expected in zip(columns, Anchor.__table__.columns):
        assert actual["nullable"] == expected.nullable
        assert actual["type"]._type_affinity is expected.type._type_affinity
