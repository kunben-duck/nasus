import importlib
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, select, text

from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.structure_job_models import StructureJobRecord, StructureWorkLeaseRecord
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_structure_jobs_api import queued, enqueue


def test_structure_jobs_ddl_and_empty_upgrade_round_trip(queued, monkeypatch):
    migration = importlib.import_module("apps.api.migrations.versions.0082_structure_jobs")
    assert engine.url.database.startswith("nasus_test_")
    schema = "nasus_test_structure_" + uuid4().hex
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            for model in (StructureJobRecord, StructureWorkLeaseRecord):
                columns = {item["name"]: item for item in inspect(connection).get_columns(model.__tablename__, schema=schema)}
                assert columns.keys() == set(model.__table__.columns.keys())
                for column in model.__table__.columns:
                    assert columns[column.name]["nullable"] == column.nullable
                    assert columns[column.name]["type"]._type_affinity is column.type._type_affinity
                    if hasattr(column.type, "timezone"):
                        assert columns[column.name]["type"].timezone == column.type.timezone
            migration.downgrade()
            assert inspect(connection).get_table_names(schema=schema) == []
            migration.upgrade()
            assert set(inspect(connection).get_table_names(schema=schema)) == {"image_structure_jobs", "image_structure_work_leases"}
        finally:
            transaction.rollback()
    assert schema not in inspect(engine).get_schema_names()


def test_populated_structural_dispatch_cannot_be_downgraded_or_backfilled(queued, monkeypatch):
    import pytest
    invocation, _ = enqueue(queued)
    migration = importlib.import_module("apps.api.migrations.versions.0082_structure_jobs")
    assert engine.url.database.startswith("nasus_test_")
    schema = "nasus_test_structure_" + uuid4().hex
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            connection.execute(text("INSERT INTO image_structure_jobs SELECT * FROM public.image_structure_jobs WHERE invocation_id = :id"), {"id": invocation})
            original = dict(connection.execute(text("SELECT * FROM image_structure_jobs")).mappings().one())
            with pytest.raises(RuntimeError, match="Cannot remove populated"):
                migration.downgrade()
            assert dict(connection.execute(text("SELECT * FROM image_structure_jobs")).mappings().one()) == original
            assert set(inspect(connection).get_table_names(schema=schema)) == {"image_structure_jobs", "image_structure_work_leases"}
            assert connection.scalar(select(StructureWorkLeaseRecord)) is None
        finally:
            transaction.rollback()
    assert schema not in inspect(engine).get_schema_names()
