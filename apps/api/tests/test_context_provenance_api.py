"""Real PG and canonical contexts; no model or target execution authorization."""
import importlib

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import delete, func, insert, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.domain.system_image.context_pack import ContextPackIntegrityError
from apps.api.app.infrastructure.persistence.context_pack_models import ContextPackRecord as Context
from apps.api.app.infrastructure.persistence.context_provenance_models import ContextProvenanceAnchorRecord as Anchor
from apps.api.app.infrastructure.persistence.relation_provenance_models import ContextRelationProvenanceRecord as RelationAnchor
from apps.api.app.infrastructure.persistence.context_provenance_projection_v1 import ContextProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.derivation_registry_models import (
    DerivationRegistryRecord, DerivationRegistryEdgeRecord, ContextQueryScopeRecord, ContextQuerySourceRecord,
)
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_acceptance_specifications_api import acceptance, documents, evidence_api
from apps.api.tests.test_context_packs_api import archive, read
from apps.api.tests.test_semantic_evaluations_api import completed
from apps.api.tests.migration_rehearsal import detach_downstream_foreign_keys, foreign_key_inventory


@pytest.fixture
def archived(acceptance):
    v = acceptance
    done = completed(archive(v)[0])
    view, url = read(v, done)
    return v, view, url


def test_canonical_context_atomically_anchors_both_immutable_graph_roots(archived):
    v, view, _ = archived
    metadata = view["metadata"]
    with session_scope() as session:
        row = session.get(Context, metadata["context_id"])
        expected = ContextProvenanceProjectorV1().verify(session, row)
        assert expected["image_revision_id"] == metadata["image_revision_id"]
        assert expected["image_artifact_hash"] == metadata["image_artifact_hash"]
        derivation = session.get(DerivationRegistryRecord, (v["project_id"], "context:" + row.context_id))
        assert derivation.content_hash == expected["context_registration_hash"]
        scope = session.get(ContextQueryScopeRecord, (v["project_id"], row.context_id))
        assert scope.query_scope_fingerprint == expected["query_scope_fingerprint"]
        assert ContextProvenanceProjectorV1().backfill(session) == 0
        assert ContextProvenanceProjectorV1().verify(session, row) == expected
        assert session.scalar(select(func.count()).select_from(Anchor).where(Anchor.project_id == v["project_id"])) == 1
    assert view["current_use"]["generation_authorized"] is False


def test_bridge_failure_rolls_back_context_registry_scope_and_outbox(acceptance, monkeypatch):
    v = acceptance
    project_event = ContextProvenanceProjectorV1.project_event

    def fail(self, session, event):
        project_event(self, session, event)
        if event.event_type == "system_image.context.compiled":
            raise ContextPackIntegrityError("injected bridge failure")

    monkeypatch.setattr(ContextProvenanceProjectorV1, "project_event", fail)
    response, _ = archive(v)
    assert response.json()["status"] == "failed", response.text
    with session_scope() as session:
        for model in (Context, Anchor, DerivationRegistryRecord, ContextQueryScopeRecord):
            assert session.scalar(select(func.count()).select_from(model).where(model.project_id == v["project_id"])) == 0
        assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_payload["correlation_id"].as_string() == v["project_id"],
            SSEEventOutboxRecord.event_type == "system_image.context.compiled")) == 0


@pytest.mark.parametrize("mutation", ["missing", "input_digest", "query_scope_fingerprint", "manifest_hash"])
def test_historical_read_fails_closed_on_bridge_corruption_and_restores_cleanly(archived, mutation):
    v, view, url = archived
    ident = view["metadata"]["context_id"]
    with session_scope() as session:
        row = session.get(Anchor, (v["project_id"], ident))
        values = {column.name: getattr(row, column.name) for column in Anchor.__table__.columns}
        session.execute(text("ALTER TABLE system_image_context_provenance_anchors DISABLE TRIGGER USER"))
        if mutation == "missing":
            dependent = session.get(RelationAnchor, (v["project_id"], ident))
            dependent_values = {c.name: getattr(dependent, c.name) for c in RelationAnchor.__table__.columns}
            session.execute(text("ALTER TABLE system_image_context_relation_anchors DISABLE TRIGGER USER"))
            session.execute(delete(RelationAnchor).where(RelationAnchor.project_id == v["project_id"], RelationAnchor.context_id == ident))
            session.execute(text("ALTER TABLE system_image_context_relation_anchors ENABLE TRIGGER USER"))
            session.execute(delete(Anchor).where(Anchor.project_id == v["project_id"], Anchor.context_id == ident))
        else:
            session.execute(update(Anchor).where(Anchor.project_id == v["project_id"], Anchor.context_id == ident)
                .values(**{mutation: "sha256:" + "0" * 64}))
        session.execute(text("ALTER TABLE system_image_context_provenance_anchors ENABLE TRIGGER USER"))
    try:
        response = v["client"].get(url, headers=v["headers"])
        assert response.status_code == 502, response.text
        assert response.json()["detail"]["error"]["code"] == "context_integrity_failed"
        assert "metadata" not in response.json() and "context" not in response.json()
        assert v["client"].get(url).status_code == 401
        assert v["client"].get(url, headers=v["member_headers"]).status_code == 403
    finally:
        with session_scope() as session:
            session.execute(text("ALTER TABLE system_image_context_provenance_anchors DISABLE TRIGGER USER"))
            if mutation == "missing":
                session.execute(insert(Anchor).values(values))
                session.execute(insert(RelationAnchor).values(dependent_values))
            else:
                session.execute(update(Anchor).where(Anchor.project_id == v["project_id"], Anchor.context_id == ident)
                    .values(**{mutation: values[mutation]}))
            session.execute(text("ALTER TABLE system_image_context_provenance_anchors ENABLE TRIGGER USER"))
    assert v["client"].get(url, headers=v["headers"]).status_code == 200


def test_database_rejects_mutation_and_wrong_project_or_registered_root_hash(archived):
    v, view, _ = archived
    ident = view["metadata"]["context_id"]
    for statement in (update(Anchor).where(Anchor.project_id == v["project_id"]).values(manifest_hash="changed"),
            delete(Anchor).where(Anchor.project_id == v["project_id"])):
        with pytest.raises(IntegrityError, match="append-only"), session_scope() as session:
            session.execute(statement)
    with session_scope() as session:
        row = session.get(Anchor, (v["project_id"], ident))
        values = {column.name: getattr(row, column.name) for column in Anchor.__table__.columns}
    # Remove only within a rolled-back transaction so the real key is available
    # to test endpoint hash FKs rather than merely a duplicate primary key.
    for changes in ({"project_id": "foreign"}, {"context_registration_hash": "sha256:" + "0" * 64},
            {"image_provenance_hash": "sha256:" + "0" * 64}):
        with pytest.raises(IntegrityError), session_scope() as session:
            session.execute(text("ALTER TABLE system_image_context_relation_anchors DISABLE TRIGGER USER"))
            session.execute(delete(RelationAnchor).where(RelationAnchor.project_id == v["project_id"], RelationAnchor.context_id == ident))
            session.execute(text("ALTER TABLE system_image_context_provenance_anchors DISABLE TRIGGER USER"))
            session.execute(delete(Anchor).where(Anchor.project_id == v["project_id"], Anchor.context_id == ident))
            session.execute(insert(Anchor).values({**values, **changes}))


class RollbackProbe(RuntimeError):
    pass


def reset_bridge(scoped_op):
    # Rehearse the historical migration inside a transaction which is always
    # rolled back; preserve the new FK protection in normal runtime tests.
    from apps.api.tests.test_relation_provenance_api import reset_relations
    migration = importlib.import_module("apps.api.migrations.versions.0071_context_provenance")
    detach_downstream_foreign_keys(scoped_op.get_bind(), scoped_op,
        (migration.TABLE, "system_image_derivations"))
    reset_relations(scoped_op)
    scoped_op.drop_table(migration.TABLE)
    scoped_op.execute("DROP FUNCTION nasus_reject_context_provenance_mutation()")
    scoped_op.drop_constraint(migration.PIN, "system_image_derivations", type_="unique")
    return migration


def test_populated_migration_backfills_without_rewriting_old_graphs_or_contexts(archived, monkeypatch):
    v, view, url = archived
    ident = view["metadata"]["context_id"]
    with session_scope() as session:
        expected = ContextProvenanceProjectorV1().verify(session, session.get(Context, ident))
    with engine.connect() as connection:
        foreign_keys = foreign_key_inventory(connection)
    with pytest.raises(RollbackProbe), engine.begin() as connection:
        scoped_op = Operations(MigrationContext.configure(connection))
        migration = reset_bridge(scoped_op)
        monkeypatch.setattr(migration, "op", scoped_op)
        migration.upgrade()
        with pytest.raises(RuntimeError, match="Cannot discard"):
            migration.downgrade()
        from sqlalchemy.orm import Session
        with Session(bind=connection) as session:
            assert ContextProvenanceProjectorV1().verify(session, session.get(Context, ident)) == expected
        raise RollbackProbe()
    with engine.connect() as connection:
        assert foreign_key_inventory(connection) == foreign_keys
    assert v["client"].get(url, headers=v["headers"]).json() == view


def test_corrupt_existing_query_scope_aborts_backfill_and_ddl_atomically(archived, monkeypatch):
    v, view, url = archived
    ident = view["metadata"]["context_id"]
    with engine.connect() as connection:
        foreign_keys = foreign_key_inventory(connection)
    with pytest.raises(ContextPackIntegrityError), engine.begin() as connection:
        scoped_op = Operations(MigrationContext.configure(connection))
        migration = reset_bridge(scoped_op)
        monkeypatch.setattr(migration, "op", scoped_op)
        connection.execute(text("ALTER TABLE system_image_context_query_scopes DISABLE TRIGGER USER"))
        connection.execute(update(ContextQueryScopeRecord).where(ContextQueryScopeRecord.project_id == v["project_id"],
            ContextQueryScopeRecord.context_id == ident).values(query_scope_fingerprint="sha256:" + "0" * 64))
        migration.upgrade()
    with engine.connect() as connection:
        assert foreign_key_inventory(connection) == foreign_keys
    assert v["client"].get(url, headers=v["headers"]).json() == view


def test_fixed_historical_ddl_preserves_column_order_nullability_and_native_types():
    inspector = inspect(engine)
    for model in (DerivationRegistryRecord, DerivationRegistryEdgeRecord, ContextQueryScopeRecord, ContextQuerySourceRecord):
        columns = inspector.get_columns(model.__tablename__)
        assert [column["name"] for column in columns] == list(model.__table__.columns.keys())
        for actual, expected in zip(columns, model.__table__.columns):
            assert actual["nullable"] == expected.nullable
            assert actual["type"]._type_affinity is expected.type._type_affinity
