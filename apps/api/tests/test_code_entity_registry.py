from __future__ import annotations

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import importlib.util
from pathlib import Path
from uuid import UUID

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.application.system_image.code_entity_registry import CodeEntityRegistrationService, legacy_code_object_id
from apps.api.app.application.system_image.source_ports import SourceTextUnit
from apps.api.app.infrastructure.persistence import code_entity_repository as module
from apps.api.app.infrastructure.persistence.code_entity_models import (
    CodeEntityIdentityRecord, CodeEntityRevisionRecord, CodeEntityProviderBindingRecord,
)
from apps.api.app.infrastructure.persistence.code_alias_models import CodeObjectAliasRecord
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord
from apps.api.app.infrastructure.system_image.code_identity_normalization import attach_symbol_keys
from apps.api.tests.test_code_symbol_identity import analyze, external, named
from apps.api.tests.test_source_snapshot_repository import pg_repo, source, artifact, indexed


@pytest.fixture
def registry(pg_repo, monkeypatch):
    snapshots, sessions = pg_repo
    migrations = []
    for name in ("0032_code_entity_registry", "0033_source_evidence", "0069_code_object_aliases"):
        path = Path(__file__).resolve().parents[1] / f"migrations/versions/{name}.py"
        spec = importlib.util.spec_from_file_location(name, path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migrations.append(migration)
    engine = sessions.kw["bind"]
    with engine.begin() as conn:
        for migration in migrations:
            migration.op = Operations(MigrationContext.configure(conn))
            migration.upgrade()

    @contextmanager
    def scoped_session():
        with sessions.begin() as session:
            yield session

    monkeypatch.setattr(module, "session_scope", scoped_session)
    from apps.api.app.infrastructure.persistence import source_evidence_repository
    from apps.api.app.infrastructure.persistence import code_alias_repository
    monkeypatch.setattr(source_evidence_repository, "session_scope", scoped_session)
    monkeypatch.setattr(code_alias_repository, "session_scope", scoped_session)
    yield CodeEntityRegistrationService(module.CodeEntityRepository()), snapshots, sessions
    with engine.begin() as conn:
        # This schema belongs only to this fixture. Production downgrade must
        # reject populated aliases; fixture teardown discards the whole schema.
        CodeObjectAliasRecord.__table__.drop(conn)
        conn.execute(text("DROP FUNCTION nasus_reject_code_alias_mutation()"))
        for table, constraint in (("code_entity_revisions", "uq_code_alias_revision_pin"),
                                  ("code_entity_provider_bindings", "uq_code_alias_mapping_pin")):
            conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}"))
        for migration in reversed(migrations[:2]):
            migration.op = Operations(MigrationContext.configure(conn))
            migration.downgrade()


def capture(registry, text="class A { void load(int x){} }\n", seed="a", project="project", source_id="source"):
    service, snapshots, _ = registry
    item = source(project=project, source_id=source_id)
    snapshot = artifact(seed)
    snapshots.record_capture(item, snapshot, captured_at="2026-09-09T00:00:00Z")
    item = indexed(item, snapshot)
    units = [SourceTextUnit("sample.java", text, len(text.encode()), snapshot.content_hash)]
    return service, item, units, analyze(text)


def register(service, item, units, result):
    return service.register(item, result, units, captured_at="2026-09-09T01:00:00Z")


def test_uuid_identity_survives_line_change_and_source_revision(registry):
    service, item, units, result = capture(registry)
    old = register(service, item, units, result)
    _, item2, units2, result2 = capture(registry, "// moved\nclass A {\n void load(int renamed){ }\n}\n", "b")
    new = register(service, item2, units2, result2)
    first, second = old[named(result, "load")[0].provider_node_id], new[named(result2, "load")[0].provider_node_id]
    assert UUID(first.entity_id).version == 4
    assert first.entity_id == second.entity_id
    assert first.entity_revision_id != second.entity_revision_id
    assert first.source_revision_id != second.source_revision_id
    with registry[2]() as session:
        before = session.get(CodeEntityRevisionRecord, first.entity_revision_id)
        after = session.get(CodeEntityRevisionRecord, second.entity_revision_id)
        assert before.payload["locator"]["start_line"] == 1
        assert after.payload["locator"]["start_line"] == 3


def test_provider_replacement_and_retries_reuse_uuid_and_revision(registry):
    service, item, units, result = capture(registry)
    old = register(service, item, units, result)
    replacement = attach_symbol_keys(external(result), result)
    new = register(service, item, units, replacement)
    assert list(old.values()) == list(new.values())
    assert register(service, item, units, replacement) == new
    with registry[2]() as session:
        assert session.scalar(select(func.count()).select_from(CodeEntityIdentityRecord)) == len(old)
        assert session.scalar(select(func.count()).select_from(CodeEntityRevisionRecord)) == len(old)
        assert session.scalar(select(func.count()).select_from(CodeEntityProviderBindingRecord)) == len(old) * 2
        assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_type == "system_image.code_entities.registered")) == 1
        aliases = session.scalars(select(CodeEntityProviderBindingRecord).where(
            CodeEntityProviderBindingRecord.provider == result.provider)).all()
        assert {row.legacy_object_id for row in aliases} == {
            legacy_code_object_id(item.project_id, item.id, node_id) for node_id in old
        }


def test_bindings_and_projects_never_share_ids(registry):
    collected = []
    for project, binding in [("project", "one"), ("project", "two"), ("other", "one")]:
        service, item, units, result = capture(registry, project=project, source_id=binding)
        collected.extend(ref.entity_id for ref in register(service, item, units, result).values())
    assert len(set(collected)) == len(collected)


def test_reject_foreign_source_revision_and_overwriting_history(registry):
    service, item, units, result = capture(registry)
    registered = register(service, item, units, result)
    foreign_source = item.model_copy(update={"project_id": "foreign"})
    assert register(service, foreign_source, units, result) == {}
    with registry[2]() as session:
        row = session.get(CodeEntityRevisionRecord, next(iter(registered.values())).entity_revision_id)
        data = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    with pytest.raises(IntegrityError):
        with registry[2].begin() as session:
            session.execute(insert(CodeEntityRevisionRecord).values({**data, "entity_revision_id": "foreign", "project_id": "foreign"}))
    for record in (CodeEntityIdentityRecord, CodeEntityRevisionRecord, CodeEntityProviderBindingRecord, CodeObjectAliasRecord):
        with pytest.raises(IntegrityError, match="append-only"):
            with registry[2].begin() as session:
                session.execute(update(record).values(project_id="foreign"))


def test_outbox_failure_rolls_back_whole_registration(registry, monkeypatch):
    service, item, units, result = capture(registry)

    def fail(*args, **kwargs):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(module.EventOutboxRepository, "append", fail)
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        register(service, item, units, result)
    with registry[2]() as session:
        for record in (CodeEntityIdentityRecord, CodeEntityRevisionRecord, CodeEntityProviderBindingRecord, CodeObjectAliasRecord):
            assert session.scalar(select(func.count()).select_from(record)) == 0


def test_legacy_unverified_and_ambiguous_do_not_gain_verified_ids(registry):
    service, item, units, result = capture(registry)
    assert register(service, item.model_copy(update={"content_ref": "legacy:missing"}), units, result) == {}
    ambiguous = replace(result, entities=tuple(replace(entity, identity_status="ambiguous") for entity in result.entities))
    assert register(service, item, units, ambiguous) == {}


def test_application_rejects_invalid_location_and_key(registry):
    service, item, units, result = capture(registry)
    method = named(result, "load")[0]
    with pytest.raises(ValueError, match="outside source text"):
        register(service, item, units, replace(result, entities=(replace(method, end_line=9999),)))
    with pytest.raises(ValueError, match="does not match"):
        register(service, item, units, replace(result, entities=(replace(method, name="other"),)))


def test_concurrent_registration_converges_to_one_identity_and_revision(registry):
    service, item, units, result = capture(registry)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: register(service, item, units, result), range(4)))
    assert all(value == results[0] for value in results)
    with registry[2]() as session:
        assert session.scalar(select(func.count()).select_from(CodeEntityIdentityRecord)) == len(results[0])
        assert session.scalar(select(func.count()).select_from(CodeEntityRevisionRecord)) == len(results[0])
