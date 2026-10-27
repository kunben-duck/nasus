import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/api/app"


def test_context_anchor_domain_has_no_provider_or_persistence_dependencies():
    source = (APP / "domain/system_image/context_provenance.py").read_text()
    for forbidden in ("sqlalchemy", "fastapi", "boto3", "infrastructure", "temporalio", "langgraph"):
        assert forbidden not in source


def test_bridge_projection_cannot_commit_or_read_private_artifacts_or_grant_authority():
    source = (APP / "infrastructure/persistence/context_provenance_projection_v1.py").read_text()
    for forbidden in ("artifact_ref", "source_excerpt", "LLMCall", "session_scope", "Repository", "generation_authorized"):
        assert forbidden not in source
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if node.func.value.id == "session":
                assert node.func.attr not in {"commit", "rollback", "update", "delete", "merge"}
    outbox = (APP / "infrastructure/persistence/event_outbox_repository.py").read_text()
    assert outbox.index("DerivationRegistryProjector().project_event") < outbox.index("ContextProvenanceProjectorV1().project_event")


def test_historical_ddl_is_fixed_and_new_bridge_uses_additive_hash_pins():
    old = (ROOT / "apps/api/migrations/versions/0068_derivation_registry.py").read_text()
    assert "Base.metadata" not in old and "op.create_table" in old
    new = (ROOT / "apps/api/migrations/versions/0071_context_provenance.py").read_text()
    assert 'down_revision = "0070_object_provenance"' in new
    assert "context_registration_hash" in new and "image_provenance_hash" in new
    assert "BEFORE UPDATE OR DELETE" in new and "Cannot discard" in new
    assert ".backfill(session)" in new
