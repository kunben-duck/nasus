"""Actual PG fencing plus real protocol/native index rebuilding, not job mocks."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import timedelta
import json
import os
import select as io_select
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update, delete, insert, text, inspect as inspect_database
from sqlalchemy.exc import IntegrityError

from apps.api.app.application.system_image.code_index_generations import CodeIndexGenerationApplicationService, code_unit_snapshot_hash
from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.application.system_image.source_ports import code_projection_payload
from apps.api.app.domain.system_image.code_index import CodeIndexCancelled
from apps.api.app.domain.system_image.code_index_generation import CodeIndexBusy, CodeIndexLeaseLost
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.domain.system_image.code_provider import projection_payload
from apps.api.app.infrastructure.persistence.code_index_generation_models import (
    CodeIndexGenerationRecord, CodeIndexWorkerLeaseRecord, CodeIndexWorkerAttemptRecord, CodeIndexProjectionRecord, CodeIndexProtocolRecord,
)
from apps.api.app.infrastructure.persistence.code_index_generation_repository import CodeIndexGenerationRepository
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.tests.test_code_graph_enrichment import _adapter, _config, _fake_codebase_memory
from apps.api.tests.test_code_graph_execution_control import stalled_provider
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_code_graph_dependencies import projection_runtime, source_tree
from apps.api.tests.exweb_projection_dependencies import verify_projection_dependencies


@pytest.fixture
def pg_index(tmp_path, monkeypatch):
    if engine.dialect.name != "postgresql":
        pytest.skip("run with the isolated PostgreSQL test runner")
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("class PaymentService:\n    def authorize(self):\n        return True\n\n# POST /payments\n# route\n")
    storage = ObjectStorage(ObjectStorageConfig(None, "probe", None, None, "us-east-1", tmp_path / "objects"))
    reader = SourceIngestionService(object_storage=storage, snapshot_cache_dir=tmp_path / "restored-one")
    source = RawAssetRecord(id="source_" + uuid4().hex, project_id="index_" + uuid4().hex,
        source_type="code", source_uri=str(root), ingestion_status="indexed")
    capture = reader._ingest_local_path(source, root, enforce_allowed_root=False, external_revision="fixed-test-revision")
    source = source.model_copy(update={"content_ref": capture.content_ref, "content_hash": capture.content_hash})
    SourceSnapshotRepository().record_capture(source, capture.snapshot, captured_at="2026-10-07T00:00:00+00:00")
    invocation = uuid4().hex
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=invocation, tool_id="system_image.build.structure", status="running",
            summary="isolated code index test", input_payload={"project_id": source.project_id}))
    binary, log = _fake_codebase_memory(tmp_path)
    monkeypatch.setenv("FAKE_CBM_CALL_LOG", str(log))
    factory = _adapter(_config(binary))
    repo = CodeIndexGenerationRepository()
    service = CodeIndexGenerationApplicationService(repo, reader, factory)
    return dict(source=source, reader=reader, storage=storage, service=service, factory=factory,
                repository=repo, invocation=invocation, log=log, tmp=tmp_path)


def opened(v):
    return v["service"].open_index(v["source"], invocation_id=v["invocation"], check_current=lambda: None)


def test_executable_copy_race_cannot_escape_the_persistent_generation_pin(pg_index, monkeypatch):
    from apps.api.app.infrastructure.system_image import codebase_memory_index_session as module
    from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryError
    v = pg_index
    source = Path(v["factory"].config.binary)
    original = source.read_bytes()
    stage = module.stage_code_graph_executable

    def changed_during_copy(*args, **kwargs):
        source.write_bytes(original + b"\n# a different installed build during the snapshot\n")
        try:
            return stage(*args, **kwargs)
        finally:
            source.write_bytes(original)

    monkeypatch.setattr(module, "stage_code_graph_executable", changed_during_copy)
    index = opened(v)
    assert index._session._provider_fingerprint == index.generation.provider_fingerprint
    with pytest.raises(CodebaseMemoryError, match="executable.*changed"):
        with index:
            pytest.fail("a mismatched executable must not become queryable")
    assert not v["log"].exists() and source.read_bytes() == original
    assert not index._session._root.exists() and not index._session._cache.exists()
    with session_scope() as session:
        assert session.get(CodeIndexProtocolRecord, index.generation.generation_id) is None
        assert session.get(CodeIndexProjectionRecord, index.generation.generation_id) is None
        lease = session.get(CodeIndexWorkerLeaseRecord, index.generation.generation_id)
        assert lease.state == "failed" and lease.owner_id is None


def test_pg_generation_reopens_from_archive_after_native_cache_and_source_are_gone(pg_index):
    v = pg_index
    with opened(v) as first:
        pin = first.generation
        before = first.read_projection()
        old_cursor = first.entities(limit=1).next_cursor
        root, cache = first._session._root, first._session._cache
    assert not root.exists() and not cache.exists()
    Path(v["source"].source_uri, "payments.py").unlink()
    reader = SourceIngestionService(object_storage=v["storage"], snapshot_cache_dir=v["tmp"] / "restored-two")
    restarted = CodeIndexGenerationApplicationService(CodeIndexGenerationRepository(), reader, _adapter(v["factory"].config))
    with restarted.reopen(pin.project_id, pin.generation_id, check_current=lambda: None) as second:
        assert second.generation == pin and second.lease.epoch == 2
        assert second._session._source_root != first._session._source_root
        assert second.read_projection() == before
        assert code_projection_payload(second.read_projection()) == code_projection_payload(before)
        assert before.native_query_observations and second.read_projection().native_query_observations
        with pytest.raises(ValueError, match="cursor"):
            second.entities(cursor=old_cursor, limit=1)
    with session_scope() as session:
        row = session.get(CodeIndexWorkerLeaseRecord, pin.generation_id)
        assert row.state == "idle" and row.owner_id is None
        assert len(session.scalars(select(CodeIndexWorkerAttemptRecord).where(
            CodeIndexWorkerAttemptRecord.generation_id == pin.generation_id)).all()) == 2
    calls = [json.loads(line)["tool"] for line in v["log"].read_text().splitlines()]
    assert calls.count("index_repository") == 2


def test_parallel_claims_have_one_owner_and_stale_worker_cannot_clear_recovered_lease(pg_index):
    v = pg_index
    with opened(v) as initial:
        pin = initial.generation
    def claim(owner):
        try:
            return CodeIndexGenerationRepository().claim(pin, owner_id=owner)
        except CodeIndexBusy:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, ("worker-a", "worker-b")))
    winner = next(item for item in claims if item is not None)
    assert sum(item is not None for item in claims) == 1
    with session_scope() as session:
        session.execute(update(CodeIndexWorkerLeaseRecord).where(CodeIndexWorkerLeaseRecord.generation_id == pin.generation_id)
            .values(lease_until=func.clock_timestamp() - timedelta(seconds=1)))
    with v["service"].reopen(pin.project_id, pin.generation_id, check_current=lambda: None) as recovered:
        assert recovered.lease.epoch == winner.epoch + 1
        with pytest.raises(CodeIndexLeaseLost):
            v["repository"].check(winner)
        assert v["repository"].release(winner) is False
        assert recovered.read_projection().entities


def test_cancel_from_another_service_prevents_reads_and_reopening(pg_index):
    v = pg_index
    first = opened(v)
    first.prepare_index()
    first.entities(limit=1)
    executable = Path(first._session._binary)
    assert executable.parent.name.startswith("nasus-cbm-exec-")
    assert executable.is_file() and executable.stat().st_mode & 0o777 == 0o500
    pin = first.generation
    other = CodeIndexGenerationApplicationService(CodeIndexGenerationRepository(), v["reader"], v["factory"])
    other.cancel(pin.project_id, pin.generation_id, check_current=lambda: None)
    with pytest.raises(CodeIndexCancelled):
        first.entities(limit=1)
    first.close()
    assert not executable.exists() and not executable.parent.exists()
    with pytest.raises(CodeIndexCancelled):
        other.reopen(pin.project_id, pin.generation_id, check_current=lambda: None)
    with session_scope() as session:
        assert session.get(CodeIndexWorkerLeaseRecord, pin.generation_id).state == "cancelled"


def test_pg_cancel_interrupts_the_actual_protocol_child(pg_index):
    v = pg_index
    binary, marker = stalled_provider(v["tmp"])
    service = CodeIndexGenerationApplicationService(v["repository"], v["reader"], _adapter(_config(binary)))
    index = service.open_index(v["source"], invocation_id=v["invocation"], check_current=lambda: None)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(index.prepare_index)
        deadline = time.monotonic() + 4
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert marker.exists()
        executable = Path(index._session._binary)
        assert executable != Path(binary) and executable.parent.name.startswith("nasus-cbm-exec-")
        assert executable.is_file() and executable.stat().st_mode & 0o777 == 0o500
        service.cancel(index.generation.project_id, index.generation.generation_id, check_current=lambda: None)
        with pytest.raises(CodeIndexCancelled):
            future.result(timeout=4)
    index.close()
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)
    assert not index._session._root.exists() and not index._session._cache.exists()
    assert not executable.exists() and not executable.parent.exists()


def test_provider_changes_and_foreign_project_cannot_reopen_or_repurpose_pins(pg_index):
    v = pg_index
    with opened(v) as first:
        pin = first.generation
    with pytest.raises(KeyError):
        v["service"].reopen("other-project", pin.generation_id, check_current=lambda: None)
    changed = _adapter(replace(v["factory"].config, index_mode="full"))
    other = CodeIndexGenerationApplicationService(v["repository"], v["reader"], changed)
    with pytest.raises(CodeIndexLeaseLost, match="provider"):
        other.reopen(pin.project_id, pin.generation_id, check_current=lambda: None)
    with pytest.raises(ValueError, match="frozen"):
        v["repository"].register(v["source"], invocation_id=v["invocation"],
            snapshot_hash="sha256:" + "a" * 64, provider_fingerprint=pin.provider_fingerprint)
    with pytest.raises(CodeIndexLeaseLost):
        v["repository"].register(v["source"].model_copy(update={"project_id": "foreign"}),
            invocation_id=v["invocation"], snapshot_hash=pin.snapshot_hash, provider_fingerprint=pin.provider_fingerprint)


def test_normal_command_retry_cannot_replace_its_provider_generation(pg_index):
    v = pg_index
    with opened(v) as first:
        pin = first.generation
        first.read_projection()
    calls = v["log"].read_text()
    changed = _adapter(replace(v["factory"].config, index_mode="full"))
    restarted = CodeIndexGenerationApplicationService(CodeIndexGenerationRepository(), v["reader"], changed)
    with pytest.raises(CodeIndexLeaseLost, match="provider"):
        with restarted.open_index(v["source"], invocation_id=v["invocation"], check_current=lambda: None):
            pytest.fail("a retry must not substitute another provider build or policy")
    assert v["log"].read_text() == calls
    with session_scope() as session:
        rows = session.scalars(select(CodeIndexGenerationRecord).where(
            CodeIndexGenerationRecord.invocation_id == v["invocation"])).all()
        assert len(rows) == 1 and rows[0].generation_id == pin.generation_id
        assert session.get(CodeIndexWorkerLeaseRecord, pin.generation_id).epoch == 1


@pytest.mark.parametrize("path", ["probe/leaf.py", "toy_grammar/binding.so"])
def test_same_version_dependency_change_requires_a_new_command_and_preserves_original_pg_pin(pg_index, projection_runtime, path):
    v = pg_index
    with opened(v) as first:
        pin = first.generation
        first.read_projection()
    calls = v["log"].read_text()
    with session_scope() as session:
        original_protocol = session.get(CodeIndexProtocolRecord, pin.generation_id).content_hash
        original_projection = session.get(CodeIndexProjectionRecord, pin.generation_id).projection_hash
    dependency = projection_runtime / path
    dependency.write_bytes(dependency.read_bytes() + b"\n# changed without a distribution version change\n")
    with pytest.raises(CodeIndexLeaseLost, match="provider"):
        v["service"].reopen(pin.project_id, pin.generation_id, check_current=lambda: None)
    with pytest.raises(CodeIndexLeaseLost, match="provider"):
        v["service"].open_index(v["source"], invocation_id=v["invocation"], check_current=lambda: None)
    assert v["log"].read_text() == calls
    with session_scope() as session:
        original = session.get(CodeIndexGenerationRecord, pin.generation_id)
        assert original.provider_fingerprint == pin.provider_fingerprint and original.content_hash == pin.content_hash
        assert session.get(CodeIndexProtocolRecord, pin.generation_id).content_hash == original_protocol
        assert session.get(CodeIndexProjectionRecord, pin.generation_id).projection_hash == original_projection
        assert session.get(CodeIndexWorkerLeaseRecord, pin.generation_id).epoch == 1
        new_invocation = uuid4().hex
        session.add(ToolInvocationRecord(id=new_invocation, tool_id="system_image.build.structure", status="running",
            summary="separate dependency generation test", input_payload={"project_id": pin.project_id}))
    with v["service"].open_index(v["source"], invocation_id=new_invocation, check_current=lambda: None) as fresh:
        assert fresh.generation.generation_id != pin.generation_id
        assert fresh.generation.provider_fingerprint != pin.provider_fingerprint
        assert fresh.read_projection().entities


@pytest.mark.parametrize("failure", [CodeIndexCancelled, PermissionError])
def test_fingerprint_control_failure_cannot_register_a_pg_generation(pg_index, projection_runtime, monkeypatch, failure):
    from apps.api.app.infrastructure.system_image import code_graph_dependencies as dependencies
    from apps.api.app.infrastructure.system_image.code_graph_dependency_files import DependencyFiles
    v, readers = pg_index, []
    def capture_reader(**kwargs):
        reader = DependencyFiles(**kwargs)
        readers.append(reader)
        return reader
    def check():
        if readers and projection_runtime / "probe/leaf.py" in readers[-1].records:
            raise failure("current-state rejection before generation registration")
    monkeypatch.setattr(dependencies, "DependencyFiles", capture_reader)
    with pytest.raises(failure):
        v["service"].open_index(v["source"], invocation_id=v["invocation"], check_current=check)
    assert not v["log"].exists()
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(CodeIndexGenerationRecord).where(
            CodeIndexGenerationRecord.invocation_id == v["invocation"])) == 0
        assert session.get(ToolInvocationRecord, v["invocation"]).status == "running"


def test_normal_command_retry_reuses_generation_but_new_confirmation_can_change_provider(pg_index):
    v = pg_index
    with opened(v) as first:
        pin, projection = first.generation, first.read_projection()
    restarted = CodeIndexGenerationApplicationService(CodeIndexGenerationRepository(), v["reader"], _adapter(v["factory"].config))
    with restarted.open_index(v["source"], invocation_id=v["invocation"], check_current=lambda: None) as retry:
        assert retry.generation == pin and retry.lease.epoch == 2
        assert retry.read_projection() == projection
    new_invocation = uuid4().hex
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=new_invocation, tool_id="system_image.build.structure", status="running",
            summary="independently confirmed index test", input_payload={"project_id": v["source"].project_id}))
    changed = CodeIndexGenerationApplicationService(CodeIndexGenerationRepository(), v["reader"],
        _adapter(replace(v["factory"].config, index_mode="full")))
    with changed.open_index(v["source"], invocation_id=new_invocation, check_current=lambda: None) as replacement:
        assert replacement.generation.generation_id != pin.generation_id
        assert replacement.generation.provider_fingerprint != pin.provider_fingerprint
        assert replacement.generation.invocation_id == new_invocation
        assert replacement.read_projection().entities


def test_normal_command_retry_cannot_substitute_a_new_revision_of_the_same_source(pg_index):
    v = pg_index
    with opened(v) as index:
        pin = index.generation
    calls = v["log"].read_text()
    root = Path(v["source"].source_uri)
    (root / "payments.py").write_text("class PaymentService:\n    def refund(self):\n        return False\n")
    capture = v["reader"]._ingest_local_path(v["source"], root, enforce_allowed_root=False,
        external_revision="independently-captured-second-revision")
    changed = v["source"].model_copy(update={"content_ref": capture.content_ref, "content_hash": capture.content_hash})
    SourceSnapshotRepository().record_capture(changed, capture.snapshot, captured_at="2026-10-07T00:01:00+00:00")
    with pytest.raises(CodeIndexLeaseLost, match="source revision"):
        v["service"].open_index(changed, invocation_id=v["invocation"], check_current=lambda: None)
    assert v["log"].read_text() == calls
    with session_scope() as session:
        rows = session.scalars(select(CodeIndexGenerationRecord).where(
            CodeIndexGenerationRecord.invocation_id == v["invocation"])).all()
        assert len(rows) == 1 and rows[0].generation_id == pin.generation_id


def test_concurrent_registration_with_different_providers_keeps_one_command_pin(pg_index):
    v = pg_index
    units = v["reader"].extract_text_units(v["source"])
    fingerprint = v["factory"].projection_fingerprint()
    def register(provider):
        try:
            return CodeIndexGenerationRepository().register(v["source"], invocation_id=v["invocation"],
                snapshot_hash=code_unit_snapshot_hash(units), provider_fingerprint=provider)
        except CodeIndexLeaseLost:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        pins = list(pool.map(register, (fingerprint, "sha256:" + "a" * 64)))
    winner = next(pin for pin in pins if pin is not None)
    assert sum(pin is not None for pin in pins) == 1
    with session_scope() as session:
        rows = session.scalars(select(CodeIndexGenerationRecord).where(
            CodeIndexGenerationRecord.invocation_id == v["invocation"])).all()
        assert len(rows) == 1 and rows[0].generation_id == winner.generation_id
    assert not v["log"].exists()


def test_database_rejects_a_second_generation_for_the_same_command_source(pg_index):
    v = pg_index
    index = opened(v)
    pin = index.generation
    index.close()
    assert any(constraint["name"] == "uq_code_index_command_binding"
        and constraint["column_names"] == ["invocation_id", "binding_id"]
        for constraint in inspect_database(engine).get_unique_constraints("code_index_generations"))
    metadata = {**asdict(pin), "generation_id": "cgen_" + uuid4().hex, "provider_fingerprint": "sha256:" + "a" * 64}
    metadata["content_hash"] = snapshot_digest({key: value for key, value in metadata.items() if key != "content_hash"})
    with pytest.raises(IntegrityError, match="uq_code_index_command_binding"):
        with session_scope() as session:
            session.add(CodeIndexGenerationRecord(**metadata))


def test_one_multisource_command_can_register_distinct_source_bindings(pg_index):
    v = pg_index
    with opened(v) as first:
        original = first.generation
    root = v["tmp"] / "second-source"
    root.mkdir()
    # Identical symbols in distinct repositories must remain distinct bindings.
    (root / "payments.py").write_bytes(Path(v["source"].source_uri, "payments.py").read_bytes())
    second = v["source"].model_copy(update={"id": "source_" + uuid4().hex, "source_uri": str(root)})
    capture = v["reader"]._ingest_local_path(second, root, enforce_allowed_root=False, external_revision="second-source-revision")
    second = second.model_copy(update={"content_ref": capture.content_ref, "content_hash": capture.content_hash})
    SourceSnapshotRepository().record_capture(second, capture.snapshot, captured_at="2026-10-07T00:01:00+00:00")
    with v["service"].open_index(second, invocation_id=v["invocation"], check_current=lambda: None) as index:
        assert index.generation.binding_id != original.binding_id
        assert index.generation.invocation_id == original.invocation_id
        assert index.generation.snapshot_hash == original.snapshot_hash
        assert index.read_projection().entities
    with session_scope() as session:
        rows = session.scalars(select(CodeIndexGenerationRecord).where(
            CodeIndexGenerationRecord.invocation_id == v["invocation"])).all()
        assert len(rows) == 2 and len({row.binding_id for row in rows}) == 2


@pytest.mark.parametrize("ambiguous", [False, True])
def test_command_pin_upgrade_preserves_history_or_rejects_ambiguity(pg_index, monkeypatch, ambiguous):
    import importlib
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    v = pg_index
    index = opened(v)
    pin = index.generation
    index.close()
    migration = importlib.import_module("apps.api.migrations.versions.0081_code_index_command")
    assert engine.url.database.startswith("nasus_test_")
    class RollbackProbe(Exception):
        pass
    schema = "nasus_test_command_pin_" + uuid4().hex
    with pytest.raises(RollbackProbe), engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        connection.execute(text("CREATE TABLE code_index_generations (LIKE public.code_index_generations INCLUDING ALL)"))
        copied = [item for item in inspect_database(connection).get_unique_constraints("code_index_generations", schema=schema)
                  if item["column_names"] == ["invocation_id", "binding_id"]]
        assert len(copied) == 1
        connection.execute(text(f'ALTER TABLE code_index_generations DROP CONSTRAINT "{copied[0]["name"]}"'))
        connection.execute(text("INSERT INTO code_index_generations SELECT * FROM public.code_index_generations WHERE generation_id = :id"),
            {"id": pin.generation_id})
        if ambiguous:
            connection.execute(text("INSERT INTO code_index_generations SELECT :id, project_id, binding_id, source_revision_id, "
                "source_manifest_hash, snapshot_hash, :fingerprint, invocation_id, content_hash FROM code_index_generations"),
                {"id": "cgen_" + uuid4().hex, "fingerprint": "sha256:" + "a" * 64})
        before = [dict(row) for row in connection.execute(text("SELECT * FROM code_index_generations ORDER BY generation_id")).mappings()]
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        if ambiguous:
            with pytest.raises(RuntimeError, match="Ambiguous code index command generations"):
                migration.upgrade()
            assert not any(item["name"] == "uq_code_index_command_binding"
                for item in inspect_database(connection).get_unique_constraints("code_index_generations", schema=schema))
        else:
            migration.upgrade()
            assert any(item["name"] == "uq_code_index_command_binding"
                for item in inspect_database(connection).get_unique_constraints("code_index_generations", schema=schema))
            with pytest.raises(RuntimeError, match="Cannot weaken populated"):
                migration.downgrade()
            connection.execute(text("DELETE FROM code_index_generations"))
            migration.downgrade()
            migration.upgrade()
            connection.execute(insert(CodeIndexGenerationRecord.__table__), before)
        assert [dict(row) for row in connection.execute(text("SELECT * FROM code_index_generations ORDER BY generation_id")).mappings()] == before
        raise RollbackProbe()
    assert schema not in inspect_database(engine).get_schema_names()


def test_generation_and_attempts_are_append_only_and_events_have_no_source_body(pg_index):
    v = pg_index
    with opened(v) as index:
        pin = index.generation
        index.entities(limit=1)
    for model, statement in ((CodeIndexGenerationRecord, update(CodeIndexGenerationRecord).values(snapshot_hash="changed")),
                             (CodeIndexGenerationRecord, delete(CodeIndexGenerationRecord)),
                             (CodeIndexWorkerAttemptRecord, delete(CodeIndexWorkerAttemptRecord)),
                             (CodeIndexProjectionRecord, delete(CodeIndexProjectionRecord)),
                             (CodeIndexProtocolRecord, update(CodeIndexProtocolRecord).values(content_hash="changed")),
                             (CodeIndexProtocolRecord, delete(CodeIndexProtocolRecord))):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement.where(model.generation_id == pin.generation_id))
    with session_scope() as session:
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == pin.generation_id)).all()
        assert len(events) == 6
        assert {item.event_type for item in events} == {"system_image.code_index." + state for state in ("registered", "claimed", "protocol_recorded", "ready", "projection_recorded", "idle")}
        assert "PaymentService" not in str([item.event_payload for item in events])


def test_protocol_pin_is_idempotent_and_changed_contract_cannot_reopen_a_generation(pg_index, monkeypatch):
    v = pg_index
    with opened(v) as index:
        pin, receipt = index.generation, index.protocol_receipt()
        index.prepare_index()
        with session_scope() as session:
            stored = session.get(CodeIndexProtocolRecord, pin.generation_id)
            assert stored.receipt == receipt.payload() and stored.content_hash == receipt.digest
            assert session.get(CodeIndexProjectionRecord, pin.generation_id) is None
            assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord).where(
                SSEEventOutboxRecord.entity_id == pin.generation_id,
                SSEEventOutboxRecord.event_type == "system_image.code_index.protocol_recorded")) == 1
    native_probe = v["factory"].negotiate_native_contract
    monkeypatch.setattr(v["factory"], "negotiate_native_contract", lambda **kwargs: replace(native_probe(**kwargs), server_version="different-contract"))
    with pytest.raises(CodeIndexLeaseLost, match="native contract"):
        with v["service"].reopen(pin.project_id, pin.generation_id, check_current=lambda: None):
            pass
    with session_scope() as session:
        assert session.get(CodeIndexProtocolRecord, pin.generation_id).content_hash == receipt.digest
        assert session.get(CodeIndexWorkerLeaseRecord, pin.generation_id).state == "failed"


def test_protocol_receipt_and_outbox_commit_atomically(pg_index, monkeypatch):
    v = pg_index
    from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
    append = EventOutboxRepository.append
    def fail_protocol_receipt(self, event, **kwargs):
        if event.event_type == "system_image.code_index.protocol_recorded":
            raise RuntimeError("receipt storage unavailable")
        return append(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail_protocol_receipt)
    index = opened(v)
    with pytest.raises(RuntimeError, match="receipt storage"):
        with index:
            pass
    with session_scope() as session:
        assert session.get(CodeIndexProtocolRecord, index.generation.generation_id) is None
        assert session.get(CodeIndexWorkerLeaseRecord, index.generation.generation_id).state == "failed"
        assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.entity_id == index.generation.generation_id,
            SSEEventOutboxRecord.event_type == "system_image.code_index.protocol_recorded")) == 0


@pytest.mark.parametrize("damage", ["missing", "hash", "payload"])
def test_corrupt_native_contract_blocks_cached_reads_without_repair(pg_index, damage):
    v = pg_index
    with opened(v) as index:
        index.read_projection()
        pin = index.generation
        with session_scope() as session:
            row = session.get(CodeIndexProtocolRecord, pin.generation_id)
            original = {column.name: getattr(row, column.name) for column in row.__table__.columns}
        assert engine.url.database.startswith("nasus_test_")
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE code_index_protocol_pins DISABLE TRIGGER USER"))
            if damage == "missing":
                connection.execute(delete(CodeIndexProtocolRecord).where(CodeIndexProtocolRecord.generation_id == pin.generation_id))
            else:
                values = {"content_hash": "sha256:" + "0" * 64} if damage == "hash" else {"receipt": {"schema": "invalid"}}
                connection.execute(update(CodeIndexProtocolRecord).where(CodeIndexProtocolRecord.generation_id == pin.generation_id).values(**values))
            connection.execute(text("ALTER TABLE code_index_protocol_pins ENABLE TRIGGER USER"))
        try:
            with pytest.raises(CodeIndexLeaseLost, match="native contract"):
                index.entities(limit=1)
            with session_scope() as session:
                row = session.get(CodeIndexProtocolRecord, pin.generation_id)
                assert (row is None) == (damage == "missing")
                if row is not None:
                    assert row.content_hash != original["content_hash"] or row.receipt != original["receipt"]
        finally:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE code_index_protocol_pins DISABLE TRIGGER USER"))
                if damage == "missing":
                    connection.execute(insert(CodeIndexProtocolRecord).values(**original))
                else:
                    connection.execute(update(CodeIndexProtocolRecord).where(CodeIndexProtocolRecord.generation_id == pin.generation_id).values(**original))
                connection.execute(text("ALTER TABLE code_index_protocol_pins ENABLE TRIGGER USER"))


def test_protocol_ddl_matches_models_and_cross_project_pin_is_rejected(pg_index):
    v = pg_index
    actual = {column["name"]: column for column in inspect_database(engine).get_columns(CodeIndexProtocolRecord.__tablename__)}
    assert set(actual) == set(CodeIndexProtocolRecord.__table__.columns.keys())
    for column in CodeIndexProtocolRecord.__table__.columns:
        assert actual[column.name]["nullable"] == column.nullable
        assert actual[column.name]["type"]._type_affinity is column.type._type_affinity
    index = opened(v)
    try:
        from apps.api.tests.test_code_graph_mcp_contract import dialogue, initialized, response, tool_contracts
        probe = dialogue()
        probe.receive(response(1, initialized()))
        probe.receive(response(2, {"tools": tool_contracts()}))
        with pytest.raises(IntegrityError):
            with session_scope() as session:
                session.add(CodeIndexProtocolRecord(generation_id=index.generation.generation_id, project_id="foreign",
                    content_hash=probe.receipt().digest, receipt=probe.receipt().payload()))
    finally:
        index.close()


def test_prepared_state_requires_actual_protocol_receipt(pg_index):
    v = pg_index
    index = opened(v)
    try:
        with pytest.raises(CodeIndexLeaseLost, match="native contract pin is missing"):
            v["repository"].mark_prepared(index.lease, state="ready")
        assert not v["log"].exists()
    finally:
        index.close()


def test_populated_predecessor_upgrade_does_not_fabricate_negotiation(pg_index, monkeypatch):
    import importlib
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    v = pg_index
    with opened(v) as index:
        pin, receipt = index.generation, index.protocol_receipt()
    migration = importlib.import_module("apps.api.migrations.versions.0080_code_index_protocol")
    assert engine.url.database.startswith("nasus_test_")
    class RollbackProbe(Exception):
        pass
    schema = "nasus_test_native_protocol_" + uuid4().hex
    with pytest.raises(RollbackProbe), engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        connection.execute(text("CREATE TABLE code_index_generations (LIKE public.code_index_generations INCLUDING ALL)"))
        connection.execute(text("INSERT INTO code_index_generations SELECT * FROM public.code_index_generations WHERE generation_id = :id"),
            {"id": pin.generation_id})
        before = dict(connection.execute(text("SELECT * FROM code_index_generations")).mappings().one())
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        assert dict(connection.execute(text("SELECT * FROM code_index_generations")).mappings().one()) == before
        assert connection.scalar(text("SELECT count(*) FROM code_index_protocol_pins")) == 0
        connection.execute(text("INSERT INTO code_index_protocol_pins VALUES (:generation, :project, :hash, CAST(:receipt AS jsonb))"),
            {"generation": pin.generation_id, "project": pin.project_id, "hash": receipt.digest,
             "receipt": json.dumps(receipt.payload())})
        with pytest.raises(RuntimeError, match="Cannot discard native code protocol receipts"):
            migration.downgrade()
        raise RollbackProbe()
    assert schema not in inspect_database(engine).get_schema_names()


@pytest.mark.parametrize("status", ["pending", "waiting_confirmation", "completed", "failed", "cancelled"])
def test_a_nonrunning_command_cannot_create_an_index_generation(pg_index, status):
    v = pg_index
    with session_scope() as session:
        session.execute(update(ToolInvocationRecord).where(ToolInvocationRecord.id == v["invocation"]).values(status=status))
    with pytest.raises(CodeIndexLeaseLost, match="canonical"):
        opened(v)
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(CodeIndexGenerationRecord).where(
            CodeIndexGenerationRecord.invocation_id == v["invocation"])) == 0
    assert not v["log"].exists()


def test_rebuilt_projection_cannot_silently_change_under_a_durable_handle(pg_index, monkeypatch):
    v = pg_index
    with opened(v) as first:
        pin = first.generation
        first.read_projection()
    with session_scope() as session:
        before = session.get(CodeIndexProjectionRecord, pin.generation_id).projection_hash
    original = v["factory"]._read_prepared_projection
    def diverged(*args, **kwargs):
        result = original(*args, **kwargs)
        return replace(result, entities=(replace(result.entities[0], name="different native observation"), *result.entities[1:]))
    monkeypatch.setattr(v["factory"], "_read_prepared_projection", diverged)
    with v["service"].reopen(pin.project_id, pin.generation_id, check_current=lambda: None) as second:
        with pytest.raises(CodeIndexLeaseLost, match="diverges"):
            second.read_projection()
    with session_scope() as session:
        assert session.get(CodeIndexProjectionRecord, pin.generation_id).projection_hash == before
        assert session.get(CodeIndexWorkerLeaseRecord, pin.generation_id).state == "failed"


def test_projection_pin_and_receipt_commit_in_one_pg_transaction(pg_index, monkeypatch):
    from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
    v = pg_index
    original = EventOutboxRepository.append
    def append(self, event, **kwargs):
        if event.event_type == "system_image.code_index.projection_recorded":
            raise RuntimeError("outbox unavailable")
        return original(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", append)
    with opened(v) as index:
        with pytest.raises(RuntimeError, match="outbox"):
            index.read_projection()
        pin = index.generation
    with session_scope() as session:
        assert session.get(CodeIndexProjectionRecord, pin.generation_id) is None
        assert session.get(CodeIndexWorkerLeaseRecord, pin.generation_id).state == "failed"


def test_revoked_authority_blocks_cached_reads_but_does_not_prevent_cleanup(pg_index):
    v = pg_index
    revoked = []
    def check():
        if revoked:
            raise PermissionError("source access revoked")
    index = v["service"].open_index(v["source"], invocation_id=v["invocation"], check_current=check)
    index.prepare_index()
    index.entities(limit=1)
    revoked.append(True)
    with pytest.raises(PermissionError):
        index.entities(limit=1)
    with pytest.raises(PermissionError):
        v["service"].cancel(index.generation.project_id, index.generation.generation_id, check_current=check)
    index.close()
    assert not index._session._root.exists() and not index._session._cache.exists()


def test_killed_worker_is_recovered_by_a_new_os_process_after_pg_lease_expiry(pg_index):
    v = pg_index
    initial = opened(v)
    pin = initial.generation
    initial.close()
    worker = r'''
import json, sys, time
from pathlib import Path
from dataclasses import asdict
from apps.api.app.application.system_image.code_index_generations import CodeIndexGenerationApplicationService
from apps.api.app.application.system_image.source_ports import code_projection_payload
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.persistence.code_index_generation_repository import CodeIndexGenerationRepository
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.tests.test_code_graph_enrichment import _adapter, _config
project, generation, binary, directory, mode = sys.argv[1:]
root = Path(directory)
storage = ObjectStorage(ObjectStorageConfig(None, "probe", None, None, "us-east-1", root / "objects"))
reader = SourceIngestionService(object_storage=storage, snapshot_cache_dir=root / ("process-" + mode))
repo = CodeIndexGenerationRepository()
repo.LEASE_SECONDS = 3  # Test lease interval; production remains 45 seconds.
service = CodeIndexGenerationApplicationService(repo, reader, _adapter(_config(Path(binary))))
with service.reopen(project, generation, check_current=lambda: None) as index:
    projection = index.read_projection()
    print(json.dumps({"generation": asdict(index.generation), "epoch": index.lease.epoch,
        "projection_hash": snapshot_digest(code_projection_payload(projection)), "pid": __import__("os").getpid()}), flush=True)
    if mode == "crash":
        time.sleep(60)
'''
    args = [sys.executable, "-c", worker, pin.project_id, pin.generation_id,
            v["factory"].config.binary, str(v["tmp"])]
    process = subprocess.Popen([*args, "crash"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert io_select.select([process.stdout], [], [], 12)[0], "worker did not prepare before timeout"
        line = process.stdout.readline()
        assert line, process.stderr.read() if process.poll() is not None else "worker did not prepare"
        first = json.loads(line)
        process.kill()
        process.wait(timeout=4)
        with pytest.raises(CodeIndexBusy):
            v["service"].reopen(pin.project_id, pin.generation_id, check_current=lambda: None)
        deadline = time.monotonic() + 5
        while True:
            with session_scope() as session:
                row = session.get(CodeIndexWorkerLeaseRecord, pin.generation_id)
                expired = row.lease_until <= session.scalar(select(func.clock_timestamp()))
            if expired:
                break
            assert time.monotonic() < deadline
            time.sleep(.05)
        restored = subprocess.run([*args, "restore"], capture_output=True, text=True, timeout=12)
        assert restored.returncode == 0, restored.stderr
        second = json.loads(restored.stdout)
        assert first["pid"] != second["pid"] and [first["epoch"], second["epoch"]] == [2, 3]
        assert first["generation"] == second["generation"] == asdict(pin)
        assert first["projection_hash"] == second["projection_hash"]
        with session_scope() as session:
            assert session.get(CodeIndexWorkerLeaseRecord, pin.generation_id).state == "idle"
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=4)


def test_canonical_confirmed_structure_build_uses_registered_native_generation(evidence_api, monkeypatch, tmp_path):
    from apps.api.app.main import app
    from apps.api.tests.test_structure_build_api import request, submit, confirm
    from apps.api.app.infrastructure.system_image.registered_code_intelligence import RegisteredCodeIntelligenceAdapter
    from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
    from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
    v = evidence_api
    extraction = app.state.container.structure_builds.preparation.extraction
    binary, log = _fake_codebase_memory(tmp_path)
    monkeypatch.setenv("FAKE_CBM_CALL_LOG", str(log))
    native = _adapter(_config(binary, mode="required"))
    generations = CodeIndexGenerationApplicationService(CodeIndexGenerationRepository(), extraction._source_reader, native)
    adapter = RegisteredCodeIntelligenceAdapter(CompositeCodeIntelligenceAdapter(
        TreeSitterCodeIntelligenceAdapter(), native, mode="required"), generations)
    monkeypatch.setattr(extraction, "_source_code_intelligence", adapter)
    invocation = submit(v, request(v))
    result = confirm(v, invocation)
    assert result["status"] == "completed", result
    with session_scope() as session:
        rows = session.scalars(select(CodeIndexGenerationRecord).where(CodeIndexGenerationRecord.invocation_id == invocation)).all()
        assert len(rows) == 1 and rows[0].project_id == v["project_id"]
        assert session.get(CodeIndexWorkerLeaseRecord, rows[0].generation_id).state == "idle"
    calls = [json.loads(line)["tool"] for line in log.read_text().splitlines()]
    assert calls.count("index_repository") == 1


def test_fixed_exweb_real_native_generation_is_rebuilt_under_same_pg_pin(pg_index):
    configured = os.environ.get("EXWEB_CODE_CONTROL_SOURCE")
    if not configured:
        pytest.skip("opt-in fixed exweb native index restart probe")
    v = pg_index
    root = Path(configured).resolve()
    revision = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    assert revision == "fe5827f6b76f77ef34918d8b452ee823142332dc"
    assert not subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
    source = v["source"].model_copy(update={"id": "exweb_" + uuid4().hex, "source_uri": str(root)})
    capture = v["reader"]._ingest_local_path(source, root, enforce_allowed_root=False, external_revision=revision)
    source = source.model_copy(update={"content_ref": capture.content_ref, "content_hash": capture.content_hash})
    SourceSnapshotRepository().record_capture(source, capture.snapshot, captured_at="2026-10-07T00:00:00+00:00")
    from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryCodeIntelligenceAdapter
    from apps.api.app.infrastructure.system_image.code_graph_process import CodeGraphProcessRunner
    tools, executable_paths = [], []
    class Recorder(CodeGraphProcessRunner):
        def run(self, args, **kwargs):
            executable_paths.append(Path(args[0]))
            tools.append("mcp/negotiate" if kwargs.get("dialogue") is not None else args[2] if len(args) > 2 else "--version")
            return super().run(args, **kwargs)
    recorder = Recorder()
    native = CodebaseMemoryCodeIntelligenceAdapter(replace(v["factory"].config,
        binary=str(Path(__file__).resolve().parents[3] / ".venv/bin/codebase-memory-mcp"), mode="required",
        timeout_seconds=180, page_size=500, max_entities=20000, max_relationships=50000), process_runner=recorder)
    service = CodeIndexGenerationApplicationService(v["repository"], v["reader"], native)
    dependency_proof = verify_projection_dependencies(native)
    with service.open_index(source, invocation_id=v["invocation"], check_current=lambda: None) as first:
        pin = first.generation
        assert pin.provider_fingerprint == dependency_proof["provider_fingerprint"]
        before = first.read_projection()
        protocol = first.protocol_receipt()
        first_root = first._session._source_root
        first_executable = Path(first._session._binary)
        assert set(executable_paths) == {first_executable}
        assert native.projection_fingerprint(executable=first_executable) == pin.provider_fingerprint
        cursor = first.entities(limit=100).next_cursor
    assert not first_executable.exists()
    first_command_count = len(executable_paths)
    reader = SourceIngestionService(object_storage=v["storage"], snapshot_cache_dir=v["tmp"] / "exweb-restart")
    service = CodeIndexGenerationApplicationService(CodeIndexGenerationRepository(), reader,
        CodebaseMemoryCodeIntelligenceAdapter(native.config, process_runner=recorder))
    with service.reopen(pin.project_id, pin.generation_id, check_current=lambda: None) as second:
        assert second.generation == pin and second.lease.epoch == 2
        assert second._session._source_root != first_root
        after = second.read_projection()
        second_executable = Path(second._session._binary)
        assert second_executable != first_executable and set(executable_paths[first_command_count:]) == {second_executable}
        assert native.projection_fingerprint(executable=second_executable) == pin.provider_fingerprint
        assert second.protocol_receipt() == protocol
        first_entities = {item.provider_node_id: asdict(item) for item in before.entities}
        next_entities = {item.provider_node_id: asdict(item) for item in after.entities}
        edge_key = lambda item: (item.from_provider_node_id, item.relationship_kind, item.to_provider_node_id)
        first_edges = {edge_key(item): asdict(item) for item in before.relationships}
        next_edges = {edge_key(item): asdict(item) for item in after.relationships}
        if after != before:
            print(json.dumps({"missing_entities": [first_entities[key] for key in sorted(first_entities.keys() - next_entities.keys())][:3],
                "new_entities": [next_entities[key] for key in sorted(next_entities.keys() - first_entities.keys())][:3],
                "missing_edge_count": len(first_edges.keys() - next_edges.keys()),
                "new_edge_count": len(next_edges.keys() - first_edges.keys()),
                "missing_edges": [first_edges[key] for key in sorted(first_edges.keys() - next_edges.keys())][:3],
                "new_edges": [next_edges[key] for key in sorted(next_edges.keys() - first_edges.keys())][:3],
                "missing_endpoints": [{"from": first_entities[edge.from_provider_node_id], "to": first_entities[edge.to_provider_node_id]}
                    for edge in before.relationships if edge_key(edge) not in next_edges][:3],
                "new_endpoints": [{"from": next_entities[edge.from_provider_node_id], "to": next_entities[edge.to_provider_node_id]}
                    for edge in after.relationships if edge_key(edge) not in first_edges][:3]}, indent=2))
        assert after == before, {"counts": [len(first_entities), len(next_entities), len(first_edges), len(next_edges)],
            "entity_sets_equal": first_entities == next_entities, "edge_sets_equal": first_edges == next_edges,
            "missing_entities": [first_entities[key] for key in first_entities.keys() - next_entities.keys()][:3],
            "new_entities": [next_entities[key] for key in next_entities.keys() - first_entities.keys()][:3],
            "changed_entities": [(first_entities[key], next_entities[key]) for key in first_entities.keys() & next_entities.keys()
                                 if first_entities[key] != next_entities[key]][:3],
            "changed_edges": [(first_edges[key], next_edges[key]) for key in first_edges.keys() & next_edges.keys()
                              if first_edges[key] != next_edges[key]][:3]}
        assert len(after.entities) > 500 and len(after.relationships) > 1000
        controller = next(item for item in after.entities if item.name == "ChatController")
        assert second.locate(controller.provider_node_id).location_precision == "exact"
        assert second.impact([controller.provider_node_id]).complete is False
        with pytest.raises(ValueError, match="cursor"):
            second.entities(cursor=cursor, limit=100)
    assert not second_executable.exists()
    report = os.environ.get("EXWEB_DURABLE_INDEX_REPORT")
    assert tools.count("index_repository") == 2
    assert tools.count("mcp/negotiate") == 2
    if report:
        Path(report).write_text(json.dumps({"schema": "nasus.exweb-durable-index-probe.v1", "git_revision": revision,
            "generation": asdict(pin), "attempt_epochs": [1, 2], "native_rebuilds": tools.count("index_repository"),
            "native_negotiations": tools.count("mcp/negotiate"), "protocol_receipt": protocol.payload(),
            "protocol_receipt_hash": protocol.digest,
            "source_roots_differ": True, "native_candidate_entities": len(before.entities),
            "native_candidate_relationships": len(before.relationships), "projection_hash": snapshot_digest(code_projection_payload(before)),
            "source_content_hash": source.content_hash, "projection_status": projection_payload(before.provider_observations)["status"],
            "scope": "source_validated_native_candidates_not_accepted_business_knowledge",
            "restart_projection_equal": True, "old_cursor_rejected": True, "target_executed": False,
            "worker_executable_snapshots": 2, "each_session_uses_one_verified_executable": True,
            "executable_snapshots_removed": True,
            "projection_dependencies": dependency_proof,
            "external_model_called": False, "business_gold": False}, indent=2) + "\n")
