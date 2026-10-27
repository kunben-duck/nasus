"""Real migration on an isolated schema, with native public facts left unchanged."""
import importlib
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import inspect as inspect_database, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.publication_provenance_models import (
    PublicationProvenanceRecord as Anchor, PublicationProvenanceDependencyRecord as Edge,
    ContextPublicationDependencyRecord as ContextAnchor,
)
from apps.api.app.infrastructure.persistence.publication_provenance_projection_v1 import PublicationProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.domain.system_image.publication import PublicationIntegrityError
from apps.api.tests.test_publication_provenance_api import inventory
from apps.api.tests.test_image_publications_api import publication, history
from apps.api.tests.test_published_image_reads import publish
from apps.api.tests.test_published_context_packs import request_for, preview_response
from apps.api.tests.test_context_packs_api import archive
from apps.api.tests.test_semantic_evaluations_api import completed
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api


class RollbackProbe(Exception):
    pass


def test_actual_migration_backfills_original_pins_idempotently_without_hash_rewrites(publication, monkeypatch):
    v = publication
    head = publish(v)
    completed(archive(v, preview_response(v, request_for(v, head)).json())[0])
    before = inventory(v)
    migration = importlib.import_module("apps.api.migrations.versions.0077_publication_provenance")
    assert engine.url.database.startswith("nasus_test_")
    with pytest.raises(RollbackProbe), engine.begin() as connection:
        schema = "nasus_test_migration_" + uuid4().hex
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        with Session(bind=connection) as session:
            projector = PublicationProvenanceProjectorV1()
            projector.backfill(session)
            rows = [dict((c.name, getattr(row, c.name)) for c in Anchor.__table__.columns) for row in
                session.scalars(select(Anchor).where(Anchor.project_id == v["project_id"]).order_by(*Anchor.__table__.primary_key.columns))]
            assert rows == before[Anchor.__tablename__]
            context_rows = [dict((c.name, getattr(row, c.name)) for c in ContextAnchor.__table__.columns) for row in
                session.scalars(select(ContextAnchor).where(ContextAnchor.project_id == v["project_id"]).order_by(ContextAnchor.context_id))]
            assert context_rows == before[ContextAnchor.__tablename__]
            count = len(session.scalars(select(Anchor)).all())
            projector.backfill(session)
            assert len(session.scalars(select(Anchor)).all()) == count
        with pytest.raises(RuntimeError, match="Cannot discard registered publication provenance"):
            migration.downgrade()
        raise RollbackProbe()
    assert history(v)["head"] == head and inventory(v) == before


def test_new_migration_native_column_types_and_nullability_match_models():
    for model in (Anchor, Edge, ContextAnchor):
        actual = {c["name"]: c for c in inspect_database(engine).get_columns(model.__tablename__)}
        assert set(actual) == set(model.__table__.columns.keys())
        for expected in model.__table__.columns:
            assert actual[expected.name]["nullable"] == expected.nullable
            assert actual[expected.name]["type"]._type_affinity is expected.type._type_affinity


def test_dependency_foreign_key_checks_original_parent_hash_not_only_opaque_id(publication):
    v = publication
    head = publish(v)
    before = inventory(v)
    with pytest.raises(IntegrityError, match="foreign key"), engine.begin() as connection:
        connection.execute(text("ALTER TABLE image_publication_dependencies DISABLE TRIGGER USER"))
        connection.execute(update(Edge).where(Edge.project_id == v["project_id"], Edge.fact_id == head["publication_id"])
            .values(parent_hash="sha256:" + "0" * 64))
    assert history(v)["head"] == head and inventory(v) == before


def test_invalid_native_ancestry_aborts_migration_and_ddl_atomically(publication, monkeypatch):
    v = publication
    head = publish(v)
    before = inventory(v)
    migration = importlib.import_module("apps.api.migrations.versions.0077_publication_provenance")
    schema = "nasus_test_migration_" + uuid4().hex
    assert engine.url.database.startswith("nasus_test_")
    with pytest.raises(PublicationIntegrityError), engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        connection.execute(text("ALTER TABLE public.image_object_provenance_edges DISABLE TRIGGER USER"))
        connection.execute(text("DELETE FROM public.image_object_provenance_edges WHERE project_id = :project AND node_key = :key"),
            {"project": v["project_id"], "key": "image_objects:" + head["image_revision_id"]})
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
    assert schema not in inspect_database(engine).get_schema_names()
    assert history(v)["head"] == head and inventory(v) == before
