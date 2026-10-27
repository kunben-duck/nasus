import importlib
from uuid import uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.gap_ownership_models import BuildGapOwnershipRecord
from apps.api.tests.test_build_gap_ownership_api import gaps, assign
from apps.api.tests.test_build_completion_api import completion
from apps.api.tests.test_investigation_api import investigation
from apps.api.tests.test_source_evidence_api import evidence_api


@pytest.mark.parametrize("populated", [False, True])
def test_additive_gap_schema_preserves_history_and_refuses_populated_downgrade(gaps, monkeypatch, populated):
    assert engine.url.database.startswith("nasus_test_")
    migration = importlib.import_module("apps.api.migrations.versions.0091_build_gap_ownership")
    ident = None
    if populated:
        result = assign(gaps).json()
        assert result["status"] == "completed", result
        ident = result["result"]["build_gap_ownership"]["revision_id"]
    schema = "nasus_test_gaps_" + uuid4().hex
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            columns = {item["name"]: item for item in inspect(connection).get_columns(BuildGapOwnershipRecord.__tablename__, schema=schema)}
            assert columns.keys() == set(BuildGapOwnershipRecord.__table__.columns.keys())
            for column in BuildGapOwnershipRecord.__table__.columns:
                assert columns[column.name]["nullable"] == column.nullable
                assert columns[column.name]["type"]._type_affinity is column.type._type_affinity
            assert connection.scalar(text("SELECT count(*) FROM image_build_gap_ownership_revisions")) == 0
            if populated:
                connection.execute(text("INSERT INTO image_build_gap_ownership_revisions SELECT * FROM public.image_build_gap_ownership_revisions WHERE revision_id = :id"), {"id": ident})
                before = dict(connection.execute(text("SELECT * FROM image_build_gap_ownership_revisions")).mappings().one())
                with pytest.raises(RuntimeError, match="Cannot discard confirmed"):
                    migration.downgrade()
                assert dict(connection.execute(text("SELECT * FROM image_build_gap_ownership_revisions")).mappings().one()) == before
            else:
                migration.downgrade()
                assert inspect(connection).get_table_names(schema=schema) == []
                migration.upgrade()
                assert connection.scalar(text("SELECT count(*) FROM image_build_gap_ownership_revisions")) == 0
        finally:
            transaction.rollback()
    assert schema not in inspect(engine).get_schema_names()
