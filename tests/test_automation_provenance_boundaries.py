import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "apps/api/app"


def test_automation_provenance_domain_does_not_depend_on_application_or_infrastructure():
    source = (ROOT / "domain/system_image/automation_provenance.py").read_text()
    tree = ast.parse(source)
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(any(name in module for name in ("application", "infrastructure", "sqlalchemy", "fastapi", "httpx")) for module in imports)


def test_script_provenance_has_an_independent_schema_and_does_not_expand_v1_kind_constraints():
    original = (ROOT / "domain/system_image/derivation_impact.py").read_text()
    assert '"script"' not in original and '"script_review"' not in original
    projector = (ROOT / "infrastructure/persistence/automation_provenance_v1.py").read_text()
    assert "def verify(" in projector and "write=False" in projector
    assert "def backfill(" in projector
    assert "quality.automation.draft_saved" in projector and "quality.automation.script_reviewed" in projector
    assert "artifact_ref" not in (ROOT / "domain/system_image/automation_provenance.py").read_text()


def test_migration_freezes_its_ddl_instead_of_importing_mutable_orm_metadata():
    migration = ROOT.parents[0] / "migrations/versions/0100_automation_provenance.py"
    source = migration.read_text()
    assert "automation_provenance_models" not in source and "__table__.create" not in source
    assert source.count("op.create_table(") == 2
    assert "Cannot discard populated automation provenance history" in source
