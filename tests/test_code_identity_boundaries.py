import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/api/app"


def test_identity_domain_and_application_ports_are_infrastructure_independent():
    for relative in ("domain/system_image/code_alias.py", "application/system_image/code_aliases.py"):
        source = (APP / relative).read_text()
        for forbidden in ("sqlalchemy", "fastapi", "boto3", "infrastructure", "temporalio", "langgraph"):
            assert forbidden not in source


def test_alias_projection_is_audited_and_uses_only_the_callers_transaction():
    source = (APP / "infrastructure/persistence/code_alias_projection_v1.py").read_text()
    for forbidden in ("session_scope", "artifact_ref", "source_excerpt", "LLM", "Repository"):
        assert forbidden not in source
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "session"):
            assert node.func.attr not in {"commit", "rollback", "delete", "merge"}
    assert "snapshot_digest(revision.payload) != revision.payload_hash" in source
    assert "legacy_code_object_id(mapping.project_id, binding.legacy_source_id, mapping.provider_node_id)" in source


def test_public_ids_use_entities_and_alias_queries_pin_frozen_membership():
    extraction = (APP / "application/system_image/context_extraction.py").read_text()
    assert "canonical_code_object_id(anchor.code_reference.entity_id)" in extraction
    repository = (APP / "infrastructure/persistence/code_alias_repository.py").read_text()
    for pin in ("source_revision_id", "entity_revision_id", "entity_id", "image_revision_id"):
        assert pin in repository
    migration = (ROOT / "apps/api/migrations/versions/0069_code_object_aliases.py").read_text()
    assert ".backfill(session)" in migration and "BEFORE UPDATE OR DELETE" in migration
    assert "Cannot discard registered code object aliases" in migration
