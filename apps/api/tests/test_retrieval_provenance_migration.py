"""Populated historical migration, exact DDL and fail-closed database constraints."""
import importlib
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import inspect as inspect_database, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.retrieval_provenance_models import (
    RetrievalProvenanceRecord as Anchor, IndexDocumentDependencyRecord as DocumentEdge,
    ContextRetrievalDependencyRecord as ContextEdge,
)
from apps.api.app.infrastructure.persistence.retrieval_provenance_projection_v1 import RetrievalProvenanceProjectorV1
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.tests.test_retrieval_provenance_api import inventory, values
from apps.api.tests.test_indexed_context_packs_api import recalled, response
from apps.api.tests.test_frozen_indexes_api import indexed
from apps.api.tests.test_image_publications_api import publication
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_context_packs_api import archive
from apps.api.tests.test_published_context_packs import request_for, preview_response
from apps.api.app.domain.system_image.context_pack import CONTEXT_POLICY
from apps.api.tests.test_semantic_evaluations_api import completed


class RollbackProbe(Exception):
    pass


def isolated_native_trace(connection):
    # Recreate the actual pre-0078 native table, not the current ORM schema.
    connection.execute(text("""CREATE TABLE image_retrieval_runs (
        retrieval_id varchar PRIMARY KEY, project_id varchar NOT NULL, generation_id varchar NOT NULL,
        publication_id varchar NOT NULL, actor_id varchar NOT NULL, scope_fingerprint varchar NOT NULL,
        query_hash varchar NOT NULL, artifact_ref varchar NOT NULL, artifact_hash varchar NOT NULL,
        created_at varchar NOT NULL,
        FOREIGN KEY (project_id, generation_id) REFERENCES public.image_index_generations (project_id, generation_id))"""))
    connection.execute(text("INSERT INTO image_retrieval_runs SELECT * FROM public.image_retrieval_runs"))


@pytest.mark.parametrize("policy", ["v1", "v4", "v5"])
def test_populated_upgrade_preserves_exact_facts_and_registration_hashes(recalled, monkeypatch, policy):
    v = recalled
    request = request_for(v, v["index_head"])
    if policy == "v1":
        request.pop("publication_id")
        request["policy_revision"] = CONTEXT_POLICY
    preview = response(v) if policy == "v5" else preview_response(v, request)
    assert preview.status_code == 200, preview.text
    completed(archive(v, preview.json())[0])
    before = inventory(v)
    assert bool(before[ContextEdge.__tablename__]) == (policy == "v5")
    migration = importlib.import_module("apps.api.migrations.versions.0078_retrieval_provenance")
    assert engine.url.database.startswith("nasus_test_")
    with pytest.raises(RollbackProbe), engine.begin() as connection:
        schema = "nasus_test_retrieval_" + uuid4().hex
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        isolated_native_trace(connection)
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        with Session(bind=connection) as session:
            for model in (Anchor, DocumentEdge, ContextEdge):
                actual = [values(row) for row in session.scalars(select(model).where(model.project_id == v["project_id"])
                    .order_by(*model.__table__.primary_key.columns))]
                assert actual == before[model.__tablename__]
            RetrievalProvenanceProjectorV1().backfill(session)
            assert [values(row) for row in session.scalars(select(Anchor).where(Anchor.project_id == v["project_id"])
                .order_by(*Anchor.__table__.primary_key.columns))] == before[Anchor.__tablename__]
        with pytest.raises(RuntimeError, match="Cannot discard registered retrieval provenance"):
            migration.downgrade()
        raise RollbackProbe()
    assert inventory(v) == before


def test_model_columns_match_actual_migration():
    for model in (Anchor, DocumentEdge, ContextEdge):
        actual = {c["name"]: c for c in inspect_database(engine).get_columns(model.__tablename__)}
        assert set(actual) == set(model.__table__.columns.keys())
        for expected in model.__table__.columns:
            assert actual[expected.name]["nullable"] == expected.nullable
            assert actual[expected.name]["type"]._type_affinity is expected.type._type_affinity


def test_generation_parent_cannot_be_null_or_point_to_wrong_hash(recalled):
    v = recalled
    before = inventory(v)
    for change in ({"parent_kind": None}, {"parent_hash": "sha256:" + "0" * 64}):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(text("ALTER TABLE image_retrieval_provenance DISABLE TRIGGER USER"))
            connection.execute(update(Anchor).where(Anchor.project_id == v["project_id"], Anchor.kind == "generation").values(**change))
    assert inventory(v) == before


def test_bad_native_vector_aborts_populated_upgrade_and_ddl(recalled, monkeypatch):
    v = recalled
    before = inventory(v)
    migration = importlib.import_module("apps.api.migrations.versions.0078_retrieval_provenance")
    schema = "nasus_test_retrieval_" + uuid4().hex
    with pytest.raises(ImageRevisionIntegrityError), engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        isolated_native_trace(connection)
        connection.execute(text("ALTER TABLE public.image_index_documents DISABLE TRIGGER USER"))
        connection.execute(text("UPDATE public.image_index_documents SET vector_hash = 'invalid' WHERE project_id = :project"),
            {"project": v["project_id"]})
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
    assert schema not in inspect_database(engine).get_schema_names()
    assert inventory(v) == before
