from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, delete, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.domain.system_image.source_snapshots import SourceSnapshotArtifact
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence import source_snapshot_repository as module
from apps.api.app.infrastructure.persistence.source_snapshot_models import (
    SourceBindingRecord, SourceRevisionRecord, SourceManifestMemberRecord, SourceManifestRecord,
)


@pytest.fixture
def pg_repo(monkeypatch):
    database_url = os.environ.get("NASUS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set NASUS_TEST_DATABASE_URL for isolated PostgreSQL schema tests")
    url = make_url(database_url)
    assert url.get_backend_name() == "postgresql", "snapshot persistence tests require PostgreSQL"
    admin = create_engine(url)
    schema = "snapshot_test_" + uuid4().hex
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url.update_query_dict({"options": f"-csearch_path={schema}"}))
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        path = Path(__file__).resolve().parents[1] / "migrations/versions/0031_source_snapshots.py"
        spec = importlib.util.spec_from_file_location("snapshot_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with engine.begin() as conn:
            migration.op = Operations(MigrationContext.configure(conn))
            migration.upgrade()
            SSEEventOutboxRecord.__table__.create(conn)
            # This fixture isolates only source tables, not the full API schema.
            conn.execute(text("CREATE TABLE raw_assets (id text PRIMARY KEY, source_type text NOT NULL)"))
            tracked = _tracked_migration(conn)
            tracked.upgrade()

        @contextmanager
        def scoped_session():
            with sessions.begin() as session:
                yield session

        monkeypatch.setattr(module, "session_scope", scoped_session)
        yield module.SourceSnapshotRepository(), sessions
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _tracked_migration(conn):
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0093_source_tracked_refs.py"
    spec = importlib.util.spec_from_file_location("tracked_source_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(conn))
    return migration


def source(kind="code", source_id="source", project="project"):
    return RawAssetRecord(id=source_id, project_id=project, source_type=kind, source_uri=f"/repo/{source_id}")


def artifact(seed="a"):
    return SourceSnapshotArtifact(
        external_revision=seed * 40, content_hash="sha256:" + seed * 64,
        manifest_hash="sha256:" + seed * 64, manifest_ref=f"s3://private/{seed}.json", file_count=1, byte_count=10,
    )


def indexed(item, snapshot):
    return item.model_copy(update={"content_ref": snapshot.manifest_ref, "content_hash": snapshot.content_hash, "ingestion_status": "indexed"})


def test_multi_source_revisions_survive_updates_and_manifest_replay(pg_repo):
    repo, sessions = pg_repo
    sources = [source("code", "repo1"), source("code", "repo2"), source("us_doc", "doc1"), source("us_doc", "doc2")]
    repo.register_bindings("project", sources)
    snapshot = artifact()
    revision_ids = [repo.record_capture(item, snapshot, captured_at="2026-09-09T00:00:00+00:00") for item in sources]
    assert len(set(revision_ids)) == 4
    first_sources = [indexed(item, snapshot) for item in sources]
    first = repo.freeze_manifest("project", first_sources, captured_at="2026-09-09T00:00:00+00:00")
    updated = artifact("b")
    repo.record_capture(sources[0], updated, captured_at="2026-09-09T01:00:00+00:00")
    second = repo.freeze_manifest("project", [indexed(sources[0], updated), *first_sources[1:]], captured_at="2026-09-09T01:00:00+00:00")
    assert first.manifest_id != second.manifest_id
    assert repo.get_manifest("project", first.manifest_id) == first
    pinned = repo.materialization_sources(first)
    assert len(pinned) == 4 and all(item.content_ref == snapshot.manifest_ref for item in pinned)
    assert {item.id for item in pinned} == {item.id for item in sources}
    assert {item.source_type for item in pinned} == {"code", "us_doc"}
    # Deliberately return to an older input: current capture != latest timestamp.
    assert repo.freeze_manifest("project", first_sources, captured_at="2026-09-09T02:00:00+00:00") == first
    assert repo.latest_manifest("project") == first
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(SourceRevisionRecord)) == 5
        assert session.scalar(select(func.count()).select_from(SourceBindingRecord)) == 4


def test_capture_is_idempotent_and_event_is_committed_once(pg_repo):
    repo, sessions = pg_repo
    first = repo.record_capture(source(), artifact(), captured_at="2026-09-09T00:00:00+00:00")
    second = repo.record_capture(source(), artifact(), captured_at="2026-09-09T01:00:00+00:00")
    assert first == second
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord)) == 1


def test_outbox_failure_rolls_back_capture(pg_repo, monkeypatch):
    repo, sessions = pg_repo
    def fail(*args, **kwargs):
        raise RuntimeError("outbox unavailable")
    monkeypatch.setattr(module.EventOutboxRepository, "append", fail)
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        repo.record_capture(source(), artifact(), captured_at="2026-09-09T00:00:00+00:00")
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(SourceRevisionRecord)) == 0


def test_cross_project_revision_and_binding_identity_changes_rejected(pg_repo):
    repo, sessions = pg_repo
    item = source()
    rid = repo.record_capture(item, artifact(), captured_at="2026-09-09T00:00:00+00:00")
    with pytest.raises(ValueError, match="cannot be overwritten"):
        repo.register_bindings("project", [item.model_copy(update={"source_uri": "/other"})])
    other = repo.freeze_manifest("other", [source(project="other")], captured_at="2026-09-09T00:00:00+00:00")
    with pytest.raises(KeyError):
        repo.get_manifest("project", other.manifest_id)
    with pytest.raises(IntegrityError, match="source_revisions"):
        with sessions.begin() as session:
            manifest_id = str(uuid4())
            session.add(SourceManifestRecord(
                manifest_id=manifest_id, project_id="other", content_hash="new",
                captured_at="2026-09-09T01:00:00+00:00",
            ))
            session.flush()
            session.add(SourceManifestMemberRecord(
                manifest_id=manifest_id, project_id="other", binding_id=other.members[0].binding_id,
                source_revision_id=rid, source_type="code", status="captured",
            ))


def test_legacy_sources_and_optional_failure_never_claim_verified_revision(pg_repo):
    repo, _sessions = pg_repo
    legacy = source().model_copy(update={"ingestion_status": "indexed", "content_ref": "nasus://raw/legacy"})
    failed = source("us_doc", "failed").model_copy(update={"ingestion_status": "failed"})
    manifest = repo.freeze_manifest("project", [legacy, failed], captured_at="2026-09-09T00:00:00+00:00")
    assert {member.status for member in manifest.members} == {"legacy_unverified", "failed"}
    assert all(member.source_revision_id is None for member in manifest.members)


def test_history_cannot_be_overwritten_or_deleted_in_postgres(pg_repo):
    repo, sessions = pg_repo
    rid = repo.record_capture(source(), artifact(), captured_at="2026-09-09T00:00:00+00:00")
    for statement in (
        update(SourceRevisionRecord).where(SourceRevisionRecord.source_revision_id == rid).values(content_hash="corrupted"),
        delete(SourceRevisionRecord).where(SourceRevisionRecord.source_revision_id == rid),
    ):
        with pytest.raises(IntegrityError, match="append-only"):
            with sessions.begin() as session:
                session.execute(statement)


def test_explicit_refs_have_independent_durable_bindings_and_historical_metadata(pg_repo):
    repo, sessions = pg_repo
    original = source()
    tracked = [original.model_copy(update={"id": name, "tracked_ref": ref}) for name, ref in (
        ("main", "refs/heads/main"), ("release", "refs/heads/release"), ("tag", "refs/tags/a"))]
    sources = [original, *tracked]
    for item in sources:
        repo.record_capture(item, artifact(), captured_at="2026-10-09T00:00:00Z")
    manifest = repo.freeze_manifest("project", [indexed(item, artifact()) for item in sources], captured_at="2026-10-09T00:00:00Z")
    restored = repo.materialization_sources(manifest)
    assert {item.id: item.tracked_ref for item in restored} == {item.id: item.tracked_ref for item in sources}
    with sessions() as session:
        rows = session.scalars(select(SourceBindingRecord)).all()
        assert len({item.binding_id for item in rows}) == len({item.identity_hash for item in rows}) == 4
        assert next(item.identity_hash for item in rows if item.legacy_source_id == original.id) == snapshot_digest([original.source_type, original.source_uri])
    with pytest.raises(ValueError, match="cannot be overwritten"):
        repo.register_bindings("project", [tracked[0].model_copy(update={"tracked_ref": "refs/heads/other"})])
    with pytest.raises(IntegrityError, match="identity is immutable"):
        with sessions.begin() as session:
            session.execute(update(SourceBindingRecord).where(SourceBindingRecord.legacy_source_id == "main")
                .values(tracked_ref="refs/heads/other"))
    with sessions.begin() as session:
        with pytest.raises(RuntimeError, match="Cannot discard populated"):
            _tracked_migration(session.connection()).downgrade()
    assert repo.get_manifest("project", manifest.manifest_id) == manifest


def test_tracking_migration_preserves_legacy_hashes_and_allows_unpopulated_downgrade(pg_repo):
    repo, sessions = pg_repo
    original = source()
    repo.register_bindings("project", [original])
    with sessions.begin() as session:
        identity = session.scalar(select(SourceBindingRecord.identity_hash))
        migration = _tracked_migration(session.connection())
        migration.downgrade()
        assert session.scalar(text("SELECT identity_hash FROM source_bindings")) == identity
        migration.upgrade()
    with sessions() as session:
        row = session.scalar(select(SourceBindingRecord))
        assert row.tracked_ref is None and row.identity_hash == snapshot_digest([original.source_type, original.source_uri])
