import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/api/app"


def test_authority_anchor_domain_remains_framework_and_provider_independent():
    source = (APP / "domain/quality_loop/authority_provenance.py").read_text()
    for forbidden in ("sqlalchemy", "fastapi", "boto3", "infrastructure", "temporalio", "langgraph"):
        assert forbidden not in source


def test_authority_projection_is_metadata_only_and_never_owns_transactions_or_decisions():
    source = (APP / "infrastructure/persistence/authority_provenance_projection_v1.py").read_text()
    for forbidden in ("artifact_ref", "source_excerpt", "session_scope", "Repository", "SSEEventOutboxRecord"):
        assert forbidden not in source
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if node.func.value.id == "session":
                assert node.func.attr not in {"commit", "rollback", "update", "delete", "merge"}
    assert 'self.facts(session, kind, (row,), write=False)' in source
    assert "new_revision == value.revision_id" in source
    outbox = (APP / "infrastructure/persistence/event_outbox_repository.py").read_text()
    assert "AuthorityProvenanceProjectorV1().project_event(session, event)" in outbox
    repository = (APP / "infrastructure/persistence/acceptance_specification_repository.py").read_text()
    assert "rows[-1:], write=False" in repository
    assert "write=True, new_revision=value.revision_id" in repository


def test_additive_ddl_freezes_authority_and_object_hashes_without_changing_prior_graphs():
    source = (ROOT / "apps/api/migrations/versions/0074_authority_provenance.py").read_text()
    assert 'down_revision = "0073_relation_fact_provenance"' in source
    assert "Base.metadata" not in source and "op.create_table" in source
    for pin in ("previous_registration_hash", "image_provenance_hash", "member_provenance_hash", "document_provenance_hash"):
        assert pin in source
    assert "BEFORE UPDATE OR DELETE" in source and "Cannot discard" in source
    assert ".backfill(session)" in source
