import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/api/app"


def test_relation_domain_has_no_framework_or_persistence_dependency():
    source = (APP / "domain/system_image/relation_provenance.py").read_text()
    for forbidden in ("sqlalchemy", "fastapi", "boto3", "infrastructure", "langgraph", "temporalio"):
        assert forbidden not in source


def test_projection_uses_the_original_transaction_and_cannot_read_private_bodies_or_grant_execution():
    source = (APP / "infrastructure/persistence/relation_provenance_projection_v1.py").read_text()
    for forbidden in ("artifact_ref", "ObjectStorage", "session_scope", "LLMCall", "generation_authorized"):
        assert forbidden not in source
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if node.func.value.id == "session":
                assert node.func.attr not in {"commit", "rollback", "delete", "update", "merge"}
    outbox = (APP / "infrastructure/persistence/event_outbox_repository.py").read_text()
    assert outbox.index("ContextProvenanceProjectorV1().project_event") < outbox.index("RelationProvenanceProjectorV1().project_event")


def test_additive_migration_preserves_older_digest_contracts_and_guarded_downgrade():
    source = (ROOT / "apps/api/migrations/versions/0072_relation_provenance.py").read_text()
    assert 'down_revision = "0071_context_provenance"' in source and "Base.metadata" not in source
    assert ".backfill(session)" in source and "BEFORE UPDATE OR DELETE" in source and "Cannot discard" in source
    assert "op.drop_constraint" not in source and "op.create_unique_constraint" not in source
