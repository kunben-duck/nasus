from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.application.system_image.code_analysis_inventory import build_code_analysis_inventory
from apps.api.app.domain.system_image.source_snapshots import SourceSnapshotArtifact, snapshot_digest
from apps.api.app.infrastructure.persistence import code_analysis_repository as module
from apps.api.app.infrastructure.persistence.code_analysis_models import CodeAnalysisRecord
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord
from apps.api.tests.test_code_analysis import analyze, unit
from apps.api.tests.test_source_snapshot_repository import pg_repo, source, indexed
from apps.api.tests.test_source_snapshot_repository import artifact
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord


@pytest.fixture
def analysis_repo(pg_repo, monkeypatch):
    snapshots, sessions = pg_repo
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0037_code_analysis.py"
    spec = importlib.util.spec_from_file_location("analysis_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with sessions.kw["bind"].begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()

    @contextmanager
    def scope():
        with sessions.begin() as session:
            yield session

    monkeypatch.setattr(module, "session_scope", scope)
    yield module.CodeAnalysisRepository(), snapshots, sessions
    with sessions.kw["bind"].begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.downgrade()


def capture(analysis_repo, text="class Orders {}", source_id="source"):
    repo, snapshots, sessions = analysis_repo
    item = source(source_id=source_id)
    code = unit("Orders.java", text)
    manifest = {"files": [{"path": code.relative_path, "content_hash": code.content_hash, "byte_count": code.byte_count}],
                "project_id": item.project_id, "source_id": item.id, "external_revision": code.content_hash}
    payload = build_code_analysis_inventory(manifest, analyze(text, "Orders.java"), [code])
    artifact = SourceSnapshotArtifact(code.content_hash, code.content_hash, snapshot_digest(manifest),
                                      f"s3://private/{code.content_hash}.json", 1, code.byte_count)
    revision_id = snapshots.record_capture(item, artifact, captured_at="2026-09-10T00:00:00Z")
    return indexed(item, artifact), payload, revision_id


def test_analysis_is_immutable_idempotent_and_bound_to_exact_revision(analysis_repo):
    repo, snapshots, sessions = analysis_repo
    item, payload, rid = capture(analysis_repo)
    first = repo.record(item, payload, captured_at="2026-09-10T00:01:00Z")
    assert repo.record(item, payload, captured_at="2026-09-10T00:02:00Z") == first
    with sessions() as session:
        row = session.scalars(select(CodeAnalysisRecord)).one()
        binding = row.binding_id
        assert row.source_revision_id == rid and row.report_hash == snapshot_digest(payload)
        events = session.scalars(select(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_type == "system_image.code_analysis.recorded")).all()
        assert len(events) == 1
        assert "Orders" not in json.dumps(events[0].event_payload) and "s3://" not in json.dumps(events[0].event_payload)
    allowed = frozenset({binding})
    for field, value in (("source_manifest_hash", "sha256:" + "0" * 64), ("external_revision", "other")):
        with pytest.raises(ValueError, match="matching immutable"):
            repo.record(item, {**payload, field: value}, captured_at="now")
    for changed_item, changed_payload in ((item.model_copy(update={"project_id": "other"}), payload),
                                         (item, {**payload, "source_id": "other"})):
        with pytest.raises(ValueError, match="scope mismatch"):
            repo.record(changed_item, changed_payload, captured_at="now")
    other, _, _ = capture(analysis_repo, "class Changed {}")
    assert other.content_hash != item.content_hash
    # Moving the captured head cannot redirect this historical observation.
    assert repo.read("project", rid, first, binding_ids=allowed)[1] == json.loads(json.dumps(payload))
    assert len(repo.list_for_revision("project", rid, binding_ids=allowed, after_id="", limit=2)) == 1
    assert repo.list_for_revision("project", rid, binding_ids=frozenset(), after_id="", limit=2) == []
    for project, revision, bindings in (("other", rid, allowed), ("project", "other", allowed), ("project", rid, frozenset())):
        with pytest.raises(KeyError):
            repo.read(project, revision, first, binding_ids=bindings)
    for statement in (update(CodeAnalysisRecord).values(recorded_at="tomorrow"), delete(CodeAnalysisRecord)):
        with pytest.raises(IntegrityError, match="append-only"):
            with sessions.begin() as session:
                session.execute(statement)


def test_analysis_outbox_failure_rolls_back_report(analysis_repo, monkeypatch):
    repo, _, sessions = analysis_repo
    item, payload, _ = capture(analysis_repo)

    def fail(*args, **kwargs):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(module.EventOutboxRepository, "append", fail)
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        repo.record(item, payload, captured_at="now")
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(CodeAnalysisRecord)) == 0


def test_failed_parse_reports_are_not_lost_and_distinct_parser_generations_are_preserved(analysis_repo):
    repo, _, sessions = analysis_repo
    item, payload, rid = capture(analysis_repo, "class Broken { void broken( {")
    assert payload["summary"]["failed"] == 1 and payload["summary"]["parsed"] == 0
    first = repo.record(item, payload, captured_at="now")
    upgraded = deepcopy(payload)
    upgraded["provider_version"] = "future-parser-version"
    second = repo.record(item, upgraded, captured_at="later")
    assert first != second
    with sessions() as session:
        rows = session.scalars(select(CodeAnalysisRecord)).all()
        assert len(rows) == 2 and all(row.source_revision_id == rid for row in rows)
        bindings = frozenset({row.binding_id for row in rows})
        values = {column.name: getattr(rows[0], column.name) for column in CodeAnalysisRecord.__table__.columns}
    first_page = repo.list_for_revision("project", rid, binding_ids=bindings, after_id="", limit=1)
    second_page = repo.list_for_revision("project", rid, binding_ids=bindings, after_id=first_page[0].analysis_id, limit=1)
    assert {first_page[0].analysis_id, second_page[0].analysis_id} == {first, second}
    assert not repo.list_for_revision("project", rid, binding_ids=bindings, after_id=second_page[0].analysis_id, limit=1)
    with pytest.raises(IntegrityError):
        with sessions.begin() as session:
            session.add(CodeAnalysisRecord(**{**values, "analysis_id": "foreign", "project_id": "foreign"}))


def test_source_revision_pages_filter_before_limit_and_omit_private_locations(analysis_repo):
    repo, snapshots, sessions = analysis_repo
    public = source(source_id="public").model_copy(update={"source_uri": "https://user:private-key@example.com/team/repo.git?token=secret"})
    hidden = source(source_id="hidden")
    rid1 = snapshots.record_capture(public, artifact("a"), captured_at="2026-09-10T01:00:00Z")
    rid2 = snapshots.record_capture(public, artifact("b"), captured_at="2026-09-10T02:00:00Z")
    hidden_rid = snapshots.record_capture(hidden, artifact("c"), captured_at="2026-09-10T03:00:00Z")
    snapshots.record_capture(source(kind="us_doc", source_id="doc"), artifact("d"), captured_at="2026-09-10T04:00:00Z")
    with sessions() as session:
        bindings = frozenset(session.scalars(select(SourceBindingRecord.binding_id).where(SourceBindingRecord.legacy_source_id != "hidden")))
    first = repo.list_source_revisions("project", binding_ids=bindings, after_id="", limit=1)
    assert len(first) == 1 and first[0].source_revision_id == rid2 and first[0].source_label == "repo.git"
    assert "private-key" not in repr(first) and "token=" not in repr(first) and "s3://" not in repr(first)
    second = repo.list_source_revisions("project", binding_ids=bindings, after_id=rid2, limit=1)
    assert len(second) == 1 and second[0].source_revision_id == rid1
    assert not repo.list_source_revisions("project", binding_ids=bindings, after_id=rid1, limit=1)
    assert not repo.list_source_revisions("other", binding_ids=bindings, after_id="", limit=1)
    with pytest.raises(KeyError):
        repo.list_source_revisions("project", binding_ids=bindings, after_id=hidden_rid, limit=1)
