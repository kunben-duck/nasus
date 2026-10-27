"""Fixed PostgreSQL DDL contracts without a database or target connection."""
import ast
import importlib
import io
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import MetaData, Table

from apps.api.app.infrastructure.persistence.run_plan_case_preparation_models import (
    RunPlanCasePreparationRecord, RunPlanCasePreparationBindingRecord,
)


def test_0119_emits_fixed_append_only_postgres_ddl_without_backfilling_commands():
    migration = importlib.import_module("apps.api.migrations.versions.0119_run_plan_case_preparations")
    stream = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": stream})
    with Operations.context(context): migration.upgrade()
    sql = stream.getvalue()
    assert migration.down_revision == "0118_run_plan_case_work" and len(migration.revision) <= 32
    assert sql.count("CREATE TABLE") == sql.count("EXECUTE FUNCTION nasus_reject_image_revision_mutation()") == 2
    assert "UNIQUE (project_id, run_id)" in sql and "UNIQUE (work_id)" in sql
    assert "REFERENCES tool_invocations" in sql and "REFERENCES quality_run_plan_case_work" in sql
    assert "REFERENCES quality_run_plan_case_preparations" in sql
    assert "INSERT INTO" not in sql and "quality_runs" not in sql
    for table in migration.TABLES:
        assert len("immutable_" + table) <= 63
        assert "BEFORE UPDATE OR DELETE ON " + table in sql


def test_fixed_migration_columns_keys_and_uniqueness_match_registered_models(monkeypatch):
    migration = importlib.import_module("apps.api.migrations.versions.0119_run_plan_case_preparations")
    tables = {}
    class Capture:
        def create_table(self, name, *parts): tables[name] = Table(name, MetaData(), *parts)
        def execute(self, _sql): pass
    monkeypatch.setattr(migration, "op", Capture())
    migration.upgrade()
    models = (RunPlanCasePreparationRecord, RunPlanCasePreparationBindingRecord)
    assert set(tables) == {model.__tablename__ for model in models}
    for model in models:
        original, generated = tables[model.__tablename__], model.__table__
        shape = lambda table: {(item.name, str(item.type), item.nullable, item.primary_key) for item in table.columns}
        fks = lambda table: {(tuple(item.column_keys), tuple(element.target_fullname for element in item.elements))
            for item in table.foreign_key_constraints}
        unique = lambda table: {tuple(item.columns.keys()) for item in table.constraints if item.__class__.__name__ == "UniqueConstraint"}
        assert shape(original) == shape(generated) and fks(original) == fks(generated) and unique(original) == unique(generated)


@pytest.mark.parametrize("populated", [0, 1])
def test_populated_downgrade_refuses_before_dropping_either_original_receipt(monkeypatch, populated):
    migration = importlib.import_module("apps.api.migrations.versions.0119_run_plan_case_preparations")
    dropped, reads = [], []
    class Capture:
        def get_bind(self): return self
        def scalar(self, query):
            reads.append(str(query))
            return len(reads) == populated + 1
        def drop_table(self, name): dropped.append(name)
    monkeypatch.setattr(migration, "op", Capture())
    with pytest.raises(RuntimeError, match="Cannot discard populated original"):
        migration.downgrade()
    assert not dropped and len(reads) == populated + 1


def test_empty_downgrade_is_reverse_order_without_deleting_original_commands(monkeypatch):
    migration = importlib.import_module("apps.api.migrations.versions.0119_run_plan_case_preparations")
    dropped = []
    class Capture:
        def get_bind(self): return self
        def scalar(self, _query): return False
        def drop_table(self, name): dropped.append(name)
    monkeypatch.setattr(migration, "op", Capture())
    migration.downgrade()
    assert dropped == list(reversed(migration.TABLES))


def test_case_preparation_domain_has_no_transport_storage_or_application_imports():
    root = Path(__file__).resolve().parents[1] / "app"
    tree = ast.parse((root / "domain/quality_loop/run_plan_case_preparation.py").read_text())
    modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not any(any(part in module.split(".") for part in
        ("infrastructure", "application", "sqlalchemy", "fastapi", "boto3", "httpx", "temporalio", "store")) for module in modules)
    source = (root.parent / "migrations/versions/0119_run_plan_case_preparations.py").read_text()
    assert "__table__" not in source and "create_all" not in source


def test_production_claim_assembly_preserves_both_bounded_context_journals():
    root = Path(__file__).resolve().parents[1] / "app"
    tree = ast.parse((root / "store.py").read_text())
    assembly = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "RuntimeAssembly")
    constructor = next(node for node in assembly.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
    assignments = [node for node in ast.walk(constructor) if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Attribute) and target.attr == "conversation_repository" for target in node.targets)]
    assert len(assignments) == 1
    value = assignments[0].value
    assert isinstance(value, ast.Call)
    hook = next(keyword.value for keyword in value.keywords if keyword.arg == "tool_claim_journal")
    assert isinstance(hook, ast.Call) and isinstance(hook.func, ast.Name) and hook.func.id == "ToolClaimJournal"
