from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_publication_provenance_domain_has_no_infrastructure_or_runtime_dependency():
    source = (ROOT / "apps/api/app/domain/system_image/publication_provenance.py").read_text()
    for forbidden in ("sqlalchemy", "infrastructure", "fastapi", "langgraph", "temporal", "httpx", "boto3"):
        assert forbidden not in source


def test_registration_is_in_original_fact_transactions_and_event_replay_is_read_only():
    repository = (ROOT / "apps/api/app/infrastructure/persistence/image_publication_repository.py").read_text()
    context = (ROOT / "apps/api/app/infrastructure/persistence/context_pack_repository.py").read_text()
    projector = (ROOT / "apps/api/app/infrastructure/persistence/publication_provenance_projection_v1.py").read_text()
    events = projector.split("def project_event", 1)[1].split("def backfill", 1)[0]
    assert "new_fact=(fact_kind, ident)" in repository
    assert "PublicationProvenanceProjectorV1().context(session, row, write=True)" in context
    assert "write=True" not in events
    assert "new_fact is None or new_fact == key" in projector
    for forbidden in ("ApprovalRecord", "ImagePublicationHeadRecord", "artifacts.read", "requests.", "httpx."):
        assert forbidden not in projector


def test_new_migration_keeps_old_facts_and_guards_destructive_downgrade():
    source = (ROOT / "apps/api/migrations/versions/0077_publication_provenance.py").read_text()
    assert 'down_revision = "0076_image_rollback"' in source
    assert "BEFORE UPDATE OR DELETE" in source and "Cannot discard registered publication provenance" in source
    assert "UPDATE image_publications" not in source and "UPDATE system_image_context_packs" not in source
