"""Additive rollback migration, historical payload compatibility and native FK guards."""
import importlib
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import inspect as inspect_database, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import BaselineRecord
from apps.api.app.infrastructure.persistence.image_publication_models import ImagePublicationRecord, ImagePublicationReviewRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_image_publications_api import publication, history, review, review_request, publish_request
from apps.api.tests.test_image_rollbacks_api import rollback, rollback_review
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_semantic_evaluations_api import invoke, completed


class RollbackProbe(Exception):
    pass


def inventory(session, project_id):
    return {model.__tablename__: [(row.payload, row.content_hash, row.rollback_publication_id) for row in
        session.scalars(select(model).where(model.project_id == project_id)).all()]
        for model in (ImagePublicationRecord, ImagePublicationReviewRecord)}


def test_legacy_publications_survive_rollback_column_upgrade_without_hash_changes(publication, monkeypatch):
    v = publication
    approval, _ = review(v)
    completed(invoke(v, "baseline.promote", publish_request(v, approval)))
    before = history(v)
    with session_scope() as session:
        original = inventory(session, v["project_id"])
    migration = importlib.import_module("apps.api.migrations.versions.0076_image_rollback")
    legacy = importlib.import_module("apps.api.migrations.versions.0053_image_publication")
    assert engine.url.database.startswith("nasus_test_")
    with pytest.raises(RollbackProbe), engine.begin() as connection:
        # Other tests may have real rollback pins; never bypass their downgrade guard.
        schema = "nasus_test_migration_" + uuid4().hex
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        connection.execute(text("CREATE TABLE baselines (LIKE public.baselines INCLUDING DEFAULTS INCLUDING CONSTRAINTS)"))
        connection.execute(text("INSERT INTO baselines SELECT * FROM public.baselines WHERE project_id = :project"),
            {"project": v["project_id"]})
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(legacy, "op", operations)
        monkeypatch.setattr(migration, "op", operations)
        legacy.upgrade()
        for model in (ImagePublicationReviewRecord, ImagePublicationRecord):
            table = model.__tablename__
            columns = ", ".join(column.name for column in model.__table__.columns if column.name != "rollback_publication_id")
            connection.execute(text(f"INSERT INTO {table} ({columns}) SELECT {columns} FROM public.{table} WHERE project_id = :project"),
                {"project": v["project_id"]})
            assert "rollback_publication_id" not in {column["name"] for column in
                inspect_database(connection).get_columns(table, schema=schema)}
        migration.upgrade()
        with Session(bind=connection) as session:
            assert inventory(session, v["project_id"]) == original
        migration.downgrade()
        assert all("rollback_publication_id" not in {column["name"] for column in
            inspect_database(connection).get_columns(model.__tablename__, schema=schema)
            } for model in (ImagePublicationRecord, ImagePublicationReviewRecord))
        migration.upgrade()
        with Session(bind=connection) as session:
            assert inventory(session, v["project_id"]) == original
        raise RollbackProbe()
    assert history(v) == before


def test_recorded_rollback_blocks_destructive_downgrade(rollback, monkeypatch):
    v = rollback
    request = rollback_review(v)
    completed(invoke(v, "baseline.rollback", request))
    before = history(v)
    migration = importlib.import_module("apps.api.migrations.versions.0076_image_rollback")
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        with pytest.raises(RuntimeError, match="Cannot discard recorded image rollback pins"):
            migration.downgrade()
    assert history(v) == before


def test_native_rollback_foreign_keys_reject_an_existing_other_baseline_publication(rollback):
    v = rollback
    baseline_id = str(uuid4())
    with session_scope() as session:
        session.add(BaselineRecord(id=baseline_id, project_id=v["project_id"], kind="version_working",
            source_version_id="rollback-other-version", updated_at="2026-10-07T01:00:00Z"))
    target = {**v["target"], "image_revision_id": v["new_publication"]["image_revision_id"],
        "image_artifact_hash": v["new_publication"]["image_artifact_hash"],
        "target_baseline_id": baseline_id, "expected_head_id": None}
    approval, _ = review(v, review_request(v, target=target))
    completed(invoke(v, "baseline.promote", publish_request(v, approval, target)))
    other = history(v, baseline_id=baseline_id)["head"]
    assert other["baseline_id"] != v["old_publication"]["baseline_id"]
    for model, record_id, constraint in (
        (ImagePublicationRecord, v["old_publication"]["publication_id"], "fk_publication_rollback"),
        (ImagePublicationReviewRecord, v["old_publication"]["approval_id"], "fk_publication_review_rollback"),
    ):
        # Disable only append-only test triggers in a rolled-back transaction, so
        # this negative assertion must reach the exact native rollback FK.
        with pytest.raises(IntegrityError, match=constraint), engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {model.__tablename__} DISABLE TRIGGER USER"))
            key = model.publication_id if model is ImagePublicationRecord else model.review_id
            connection.execute(update(model).where(key == record_id).values(rollback_publication_id=other["publication_id"]))
    assert history(v)["head"] == v["new_publication"]


def test_rollback_migration_columns_match_native_types_and_nullability():
    for model in (ImagePublicationRecord, ImagePublicationReviewRecord):
        columns = inspect_database(engine).get_columns(model.__tablename__)
        assert columns[-1]["name"] == "rollback_publication_id"
        actual_columns = {column["name"]: column for column in columns}
        assert set(actual_columns) == set(model.__table__.columns.keys())
        for expected in model.__table__.columns:
            actual = actual_columns[expected.name]
            assert actual["nullable"] == expected.nullable and actual["type"]._type_affinity is expected.type._type_affinity
