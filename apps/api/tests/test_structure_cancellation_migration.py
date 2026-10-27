import importlib
from uuid import uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.structure_cancel_models import StructureCancellationRecord
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_structure_jobs_api import queued, enqueue
from apps.api.tests.test_structure_cancellation_api import cancel


@pytest.mark.parametrize("populated", [False, True])
def test_cancellation_schema_matches_and_never_fabricates_or_drops_history(queued, monkeypatch, populated):
    migration = importlib.import_module("apps.api.migrations.versions.0083_structure_cancellation")
    assert engine.url.database.startswith("nasus_test_")
    original = None
    if populated:
        ident, payload = enqueue(queued)
        assert cancel(queued, ident, payload)["status"] == "completed"
        original = ident
    schema = "nasus_test_stop_" + uuid4().hex
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            model = StructureCancellationRecord
            columns = {item["name"]: item for item in inspect(connection).get_columns(model.__tablename__, schema=schema)}
            assert columns.keys() == set(model.__table__.columns.keys())
            for column in model.__table__.columns:
                assert columns[column.name]["nullable"] == column.nullable
                assert columns[column.name]["type"]._type_affinity is column.type._type_affinity
                if hasattr(column.type, "timezone"):
                    assert columns[column.name]["type"].timezone == column.type.timezone
            assert connection.scalar(text("SELECT count(*) FROM image_structure_cancellations")) == 0
            if populated:
                connection.execute(text("INSERT INTO image_structure_cancellations SELECT * FROM public.image_structure_cancellations WHERE original_invocation_id = :id"), {"id": original})
                before = dict(connection.execute(text("SELECT * FROM image_structure_cancellations")).mappings().one())
                with pytest.raises(RuntimeError, match="Cannot remove populated"):
                    migration.downgrade()
                assert dict(connection.execute(text("SELECT * FROM image_structure_cancellations")).mappings().one()) == before
            else:
                migration.downgrade()
                assert inspect(connection).get_table_names(schema=schema) == []
                migration.upgrade()
                assert connection.scalar(text("SELECT count(*) FROM image_structure_cancellations")) == 0
        finally:
            transaction.rollback()
    assert schema not in inspect(engine).get_schema_names()
