from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PERSISTENCE = ROOT / "apps/api/app/infrastructure/persistence"


def test_retrieval_provenance_domain_has_no_runtime_or_provider_dependency():
    source = (ROOT / "apps/api/app/domain/system_image/retrieval_provenance.py").read_text()
    for forbidden in ("sqlalchemy", "infrastructure", "fastapi", "langgraph", "temporal", "httpx", "boto3"):
        assert forbidden not in source
    assert 'RETRIEVAL_PROVENANCE_POLICY = "nasus.retrieval-provenance.v1"' in source


def test_native_fact_transactions_register_dependencies_and_reads_never_repair():
    indexes = (PERSISTENCE / "frozen_index_repository.py").read_text()
    queries = (PERSISTENCE / "context_retrieval_repository.py").read_text()
    contexts = (PERSISTENCE / "context_pack_repository.py").read_text()
    projector = (PERSISTENCE / "retrieval_provenance_projection_v1.py").read_text()
    events = projector.split("def project_event", 1)[1]
    assert 'fact(session, "reservation", row, write=True)' in indexes
    assert 'fact(session, "generation", session.get(Generation, invocation_id), write=True)' in indexes
    assert 'fact(session, "retrieval", row, write=True)' in queries
    assert 'RetrievalProvenanceProjectorV1().context(session, row, write=True)' in contexts
    assert "write=True" not in events
    assert "event.entity_version == sequence" in events and "Outbox.sequence" in events
    assert 'registered = self.fact(session, parent_kind, prior)' in projector
    assert 'PublicationProvenanceProjectorV1().fact(session, "publication", publication)' in projector
    assert "require(set(bindings) == targets)" in projector
    assert "_NATIVE_FIELDS =" in projector and "_DOCUMENT_FIELDS =" in projector
    for forbidden in ("ImagePublicationHeadRecord", "ApprovalRecord", "artifacts.read", "httpx.", "_embed("):
        assert forbidden not in projector


def test_migration_keeps_original_facts_and_guards_destructive_downgrade():
    source = (ROOT / "apps/api/migrations/versions/0078_retrieval_provenance.py").read_text()
    assert 'down_revision = "0077_publication_provenance"' in source
    assert "BEFORE UPDATE OR DELETE" in source and "Cannot discard registered retrieval provenance" in source
    for table in ("image_index_reservations", "image_index_generations", "image_index_documents",
                  "image_retrieval_runs", "system_image_context_packs"):
        assert "UPDATE " + table not in source and "DELETE FROM " + table not in source
