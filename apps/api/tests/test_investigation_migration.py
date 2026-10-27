import importlib
from uuid import uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.investigation_models import InvestigationRevisionRecord
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_investigation_api import investigation, investigate


@pytest.mark.parametrize("populated", [False, True])
def test_additive_investigation_schema_no_history_fabrication_or_destructive_downgrade(investigation, monkeypatch, populated):
    migration = importlib.import_module("apps.api.migrations.versions.0084_investigation_revisions")
    assert engine.url.database.startswith("nasus_test_")
    ident = None
    if populated:
        saved = investigate(investigation)
        assert saved["status"] == "completed", saved
        ident = saved["result"]["investigation"]["revision_id"]
    schema = "nasus_test_investigation_" + uuid4().hex
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            model = InvestigationRevisionRecord
            columns = {item["name"]: item for item in inspect(connection).get_columns(model.__tablename__, schema=schema)}
            assert columns.keys() == set(model.__table__.columns.keys())
            for column in model.__table__.columns:
                assert columns[column.name]["nullable"] == column.nullable
                assert columns[column.name]["type"]._type_affinity is column.type._type_affinity
            assert connection.scalar(text("SELECT count(*) FROM image_investigation_revisions")) == 0
            if populated:
                connection.execute(text("INSERT INTO image_investigation_revisions SELECT * FROM public.image_investigation_revisions WHERE revision_id = :id"), {"id": ident})
                before = dict(connection.execute(text("SELECT * FROM image_investigation_revisions")).mappings().one())
                with pytest.raises(RuntimeError, match="Cannot discard populated"):
                    migration.downgrade()
                assert dict(connection.execute(text("SELECT * FROM image_investigation_revisions")).mappings().one()) == before
            else:
                migration.downgrade()
                assert inspect(connection).get_table_names(schema=schema) == []
                migration.upgrade()
                assert connection.scalar(text("SELECT count(*) FROM image_investigation_revisions")) == 0
        finally:
            transaction.rollback()
    assert schema not in inspect(engine).get_schema_names()
