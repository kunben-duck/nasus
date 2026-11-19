"""Exercise incremental DDL in isolated schemas, never erase development records."""
import importlib
from uuid import uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from apps.api.app.infrastructure.persistence.test_design_result_models import TestDesignCaseEditRecord as CaseEdit
from apps.api.app.infrastructure.persistence.version_delivery_models import VersionImageAdoptionRecord as Adoption
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


@pytest.mark.parametrize("name,model", [
    ("0128_iteration_image_adoptions", Adoption), ("0129_test_design_case_edits", CaseEdit),
])
def test_empty_migration_roundtrip_retains_exact_immutable_parents(name, model):
    migration = importlib.import_module("apps.api.migrations.versions." + name)
    table = model.__table__
    with session_scope() as session:
        connection = session.connection()
        assert connection.dialect.name == "postgresql"
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        namespace = "m3_migration_" + uuid4().hex
        session.execute(text(f'CREATE SCHEMA "{namespace}"'))
        session.execute(text(f'SET LOCAL search_path TO "{namespace}", public'))
        if model is CaseEdit:
            session.execute(text("CREATE TABLE quality_test_design_results (LIKE public.quality_test_design_results INCLUDING ALL)"))
            session.execute(text("ALTER TABLE quality_test_design_results DROP CONSTRAINT ck_test_design_result_call_kind"))
            session.execute(text("ALTER TABLE quality_test_design_results ADD CONSTRAINT ck_test_design_result_call_kind CHECK "
                "((provenance_kind = 'single' AND call_id IS NOT NULL) OR (provenance_kind = 'batch' AND call_id IS NULL))"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert session.scalar(text(f'SELECT count(*) FROM "{namespace}".{table.name}')) == 0
            migration.downgrade()
            assert not inspect(connection).has_table(table.name, schema=namespace)
            migration.upgrade()
        actual = inspect(connection)
        assert {column["name"] for column in actual.get_columns(table.name, schema=namespace)} == set(table.columns.keys())
        expected = {(tuple(fk.column_keys), tuple(element.target_fullname for element in fk.elements)) for fk in table.foreign_key_constraints}
        observed = {(tuple(fk["constrained_columns"]), tuple(fk["referred_table"] + "." + key for key in fk["referred_columns"]))
            for fk in actual.get_foreign_keys(table.name, schema=namespace)}
        assert expected == observed
        assert session.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid = CAST(:table AS regclass)"),
            {"table": namespace + "." + table.name}).scalars().all() == ["immutable_" + table.name]
        session.execute(text(f'DROP SCHEMA "{namespace}" CASCADE'))
