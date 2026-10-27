import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/api/app"


def test_domain_registration_has_no_framework_or_storage_dependencies():
    source = (APP / "domain/system_image/derivation_registry.py").read_text()
    for forbidden in ("sqlalchemy", "fastapi", "boto3", "infrastructure", "temporalio", "langgraph"):
        assert forbidden not in source


def test_projection_is_metadata_only_and_only_in_the_existing_commit_transaction():
    projection = (APP / "infrastructure/persistence/derivation_registry_projection.py").read_text()
    for forbidden in ("artifact_ref", "source_excerpt", "oracle", "LLMCall", "HTTP", "session_scope", "Repository"):
        assert forbidden not in projection
    for node in ast.walk(ast.parse(projection)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "session"):
            assert node.func.attr not in {"commit", "rollback", "update", "delete", "merge"}
    outbox = (APP / "infrastructure/persistence/event_outbox_repository.py").read_text()
    assert "DerivationRegistryProjector().project_event(session, event)" in outbox
    assert outbox.index("session.flush()") < outbox.index(".project_event(session, event)")


def test_registry_consumers_detect_missing_projection_and_keep_one_sql_snapshot():
    for relative in ("source_context_root_inventory.py", "context_dependency_inventory.py"):
        source = (APP / "infrastructure/persistence" / relative).read_text()
        assert source.count("session.execute(") == 1
        assert "canonical_total" in source and "DerivationImpactIntegrityError" in source
    roots = (APP / "infrastructure/persistence/source_context_root_inventory.py").read_text()
    assert "select(total.c.total, total.c.canonical_total, page)" in roots
    assert "Node.artifact_hash == canonical.c.payload" in roots and "QueryScope.input_digest == canonical.c.payload" in roots
    migration = (ROOT / "apps/api/migrations/versions/0068_derivation_registry.py").read_text()
    assert ".backfill(session)" in migration and "BEFORE UPDATE OR DELETE" in migration
    assert "cannot downgrade while derivation provenance exists" in migration
