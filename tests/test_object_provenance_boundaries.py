import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/api/app"


def test_object_provenance_domain_remains_framework_independent():
    source = (APP / "domain/system_image/object_provenance.py").read_text()
    for forbidden in ("sqlalchemy", "fastapi", "boto3", "infrastructure", "temporalio", "langgraph"):
        assert forbidden not in source


def test_provenance_projection_cannot_read_bodies_or_open_another_transaction():
    source = (APP / "infrastructure/persistence/object_provenance_projection_v1.py").read_text()
    for forbidden in ("session_scope", "Repository", "requests", "httpx", "boto3", "LLM", "artifact_ref", "payload_ref", "manifest_ref"):
        assert forbidden not in source
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "session"):
            assert node.func.attr not in {"commit", "rollback", "update", "delete", "merge"}
    outbox = (APP / "infrastructure/persistence/event_outbox_repository.py").read_text()
    assert "ObjectProvenanceProjectorV1().project_event(session, event)" in outbox
    assert outbox.index("session.flush()") < outbox.index("ObjectProvenanceProjectorV1().project_event")


def test_current_image_read_verifies_registration_and_migration_backfill_is_append_only():
    repository = (APP / "infrastructure/persistence/image_revision_repository.py").read_text()
    assert "verify_image_provenance(session, row, members=persisted)" in repository
    verifier = (APP / "infrastructure/persistence/image_provenance_reads.py").read_text()
    assert "ObjectProvenanceProjectorV1().image(session, image, write=False, members=members)" in verifier
    assert "RelationProvenanceProjectorV1().image(session, image, write=False, native_verified=True)" in verifier
    assert "snapshot[0] is session" in verifier
    migration = (ROOT / "apps/api/migrations/versions/0070_object_provenance.py").read_text()
    assert ".backfill(session)" in migration and "BEFORE UPDATE OR DELETE" in migration
    assert "Cannot discard registered image object provenance" in migration


def test_compilation_metadata_reuse_has_a_read_only_snapshot_and_separate_bounded_pool():
    repository = (APP / "infrastructure/persistence/image_revision_repository.py").read_text()
    assert "with image_read_snapshot_scope() as session:" in repository
    assert "self._read_snapshot.reset(token)" in repository
    assert "len(verified) >= 2" in repository
    pool = (APP / "infrastructure/persistence/image_read_snapshot.py").read_text()
    assert '"isolation_level": "REPEATABLE READ"' in pool
    assert "SET TRANSACTION READ ONLY" in pool
    assert pool.index("SET TRANSACTION READ ONLY") < pool.index("_active_snapshot.set(")
    assert "pool_size=4, max_overflow=0, pool_timeout=5" in pool
    assert "session.commit(" not in pool and "SessionLocal" not in pool
