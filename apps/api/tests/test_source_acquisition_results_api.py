"""Durable acquisition fault windows on isolated PostgreSQL/private MinIO."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.system_image.raw_asset_chunks import SystemImageRawAssetChunkApplicationService
from apps.api.app.application.system_image.source_ingestion import SystemImageSourceIngestionApplicationService
from apps.api.app.application.system_image.source_refresh_inputs import source_refresh_selection
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.source_acquisition_repository import SourceAcquisitionIntentRepository
from apps.api.app.infrastructure.persistence.source_acquisition_result_models import SourceAcquisitionResultRecord as Result, SourceAcquisitionManifestRecord as Receipt
from apps.api.app.infrastructure.persistence.source_acquisition_result_models import SourceAcquisitionProgressRecord as Progress
from apps.api.app.infrastructure.persistence.source_inventory_models import SourceInventoryRecord
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceManifestRecord, SourceRevisionRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.app.main import app
from apps.api.tests.test_source_acquisition_intents_api import running_command, scope_for
from apps.api.tests.test_source_access_api import policy
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_ingestion_access_api import grant_tester, facts
from apps.api.tests.test_source_refresh_api import add_optional, read, selection


class ProcessStopped(BaseException):
    """Stop outside normal connector failure/terminal command handling."""


def operations():
    return app.state.container.system_image.source_bindings._operations


def fresh_service():
    op = operations()
    original = op.source_ingestion_use_cases
    connector = SourceIngestionService()
    return SystemImageSourceIngestionApplicationService(original._projection, connector,
        SystemImageRawAssetChunkApplicationService(op.workspace, connector), SourceSnapshotRepository(),
        source_authorization=original._authorization, acquisition_intents=SourceAcquisitionIntentRepository())


def resume(v, command, *, service=None, actor=None):
    op = operations()
    with actor_scope(UserProfile(**(actor or v["owner"]))):
        (service or fresh_service()).ingest_sources(v["project_id"], invocation_id=command["id"],
            selection=source_refresh_selection(command["input_payload"]),
            ensure_draft_state=lambda: op.ensure_state(v["project_id"], ready=False),
            source_binding_incomplete=lambda: op.source_binding_incomplete(v["project_id"]),
            missing_source_types=lambda: op.missing_source_types(v["project_id"]))


def rows(v, model):
    with session_scope() as session:
        return session.scalars(select(model).where(model.project_id == v["project_id"])).all()


def command_results(command):
    with session_scope() as session:
        return deepcopy([row.payload for row in session.scalars(select(Result).where(Result.invocation_id == command["id"]).order_by(Result.source_id))])


def acquire_events(command, kind):
    with session_scope() as session:
        return deepcopy([row.event_payload for row in session.scalars(select(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.entity_id == command["id"])).all() if row.event_payload["event_type"] == kind])


@pytest.mark.parametrize("mode", ["selected", "whole_project"])
@pytest.mark.parametrize("window", ["after_capture", "after_manifest"])
def test_original_running_command_reuses_committed_results_after_interruption(evidence_api, tmp_path, monkeypatch, mode, window):
    v = evidence_api
    optional, image, source = add_optional(v, tmp_path)
    selected = selection(image, source["id"]) if mode == "selected" else {}
    optional.write_text("# US-1\nContent captured by the original command.\n")
    v["path"].write_text("class Captured:\n    pass\n")
    command = running_command(v, selected, monkeypatch)
    service = fresh_service()
    calls = []
    original = SourceIngestionService.ingest
    def counted(connector, item):
        calls.append(item.id)
        return original(connector, item)
    monkeypatch.setattr(SourceIngestionService, "ingest", counted)
    with monkeypatch.context() as fault:
        if window == "after_capture":
            save = SourceAcquisitionIntentRepository.record_success
            def stopped(repo, *args):
                result = save(repo, *args)
                raise ProcessStopped()
            fault.setattr(SourceAcquisitionIntentRepository, "record_success", stopped)
        else:
            fault.setattr(service._raw_asset_chunks, "materialize", lambda *args, **kwargs: (_ for _ in ()).throw(ProcessStopped()))
        with pytest.raises(ProcessStopped):
            resume(v, command, service=service)
    saved = command_results(command)
    assert len(saved) == (1 if window == "after_capture" else 1 if mode == "selected" else 2)
    captured = {item["source_id"]: deepcopy(item) for item in saved}
    initial_calls = deepcopy(calls)
    previous_head = SourceSnapshotRepository().latest_manifest(v["project_id"])
    if window == "after_manifest":
        with session_scope() as session:
            assert session.get(Receipt, command["id"]).manifest_id == previous_head.manifest_id
    # Change upstream after the durable result exists. A fresh application /
    # connector / repository must use the original archive, not this new body.
    optional.write_text("# US-1\nLater mutable content must not replace captured content.\n")
    v["path"].write_text("class Later:\n    pass\n")
    resume(v, command)
    assert not any(ident in captured for ident in calls[len(initial_calls):])
    assert len(calls) == (1 if mode == "selected" else 2)
    after = facts(v)
    for source_id, result in captured.items():
        item = next(item for item in after.raw_assets if item.id == source_id)
        assert item.content_hash == result["content_hash"] and item.content_ref == result["content_ref"]
        assert item.last_ingested_at == result["acquired_at"]
        assert command_results(command)[next(i for i, row in enumerate(command_results(command)) if row["source_id"] == source_id)] == result
        units = SourceIngestionService().extract_text_units(item)
        assert not any("Later mutable" in unit.text or "class Later" in unit.text for unit in units)
    before_replay = command_results(command)
    calls_before_replay = deepcopy(calls)
    head = SourceSnapshotRepository().latest_manifest(v["project_id"])
    resume(v, command)
    assert calls == calls_before_replay
    assert command_results(command) == before_replay
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == head
    assert len(acquire_events(command, "system_image.source_acquisition.manifest_committed")) == 1
    assert len(acquire_events(command, "system_image.source_acquisition.result_recorded")) == len(before_replay)
    with session_scope() as session:
        assert session.get(ToolInvocationRecord, command["id"]).status == "running"


@pytest.mark.parametrize("window", ["after_capture", "after_manifest"])
def test_other_command_advancing_manifest_blocks_old_command_without_repair(evidence_api, monkeypatch, window):
    v = evidence_api
    command = running_command(v, selection(read(v), next(iter(scope_for(v).source_ids))), monkeypatch)
    service = fresh_service()
    with monkeypatch.context() as fault:
        if window == "after_capture":
            save = SourceAcquisitionIntentRepository.record_success
            def stopped(repo, *args):
                save(repo, *args)
                raise ProcessStopped()
            fault.setattr(SourceAcquisitionIntentRepository, "record_success", stopped)
        else:
            fault.setattr(service._raw_asset_chunks, "materialize", lambda *args, **kwargs: (_ for _ in ()).throw(ProcessStopped()))
        with pytest.raises(ProcessStopped):
            resume(v, command, service=service)
    v["path"].write_text("class NewCommand:\n    pass\n")
    v["invoke"]("system_image.sources.ingest")
    head, before, history = SourceSnapshotRepository().latest_manifest(v["project_id"]), facts(v), command_results(command)
    calls = []
    monkeypatch.setattr(SourceIngestionService, "ingest", lambda _self, source: calls.append(source.id))
    with pytest.raises(PlatformApplicationError) as error:
        resume(v, command)
    assert error.value.code == "source_acquisition_scope_changed"
    assert not calls and facts(v) == before and command_results(command) == history
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == head


@pytest.mark.parametrize("kind", ["result_recorded", "manifest_committed"])
def test_source_facts_and_receipts_rollback_with_their_outbox_transaction(evidence_api, monkeypatch, kind):
    v = evidence_api
    v["path"].write_text("class AtomicSource:\n    pass\n")
    command = running_command(v, {}, monkeypatch)
    counts = {model: len(rows(v, model)) for model in (Result, SourceRevisionRecord, SourceInventoryRecord, Receipt, SourceManifestRecord)}
    head = SourceSnapshotRepository().latest_manifest(v["project_id"])
    append = EventOutboxRepository.append
    def fail(repo, event, *args, **kwargs):
        if event.event_type == f"system_image.source_acquisition.{kind}":
            raise OSError("private-storage-credential-fault")
        return append(repo, event, *args, **kwargs)
    with monkeypatch.context() as fault:
        fault.setattr(EventOutboxRepository, "append", fail)
        with pytest.raises(PlatformApplicationError) as error:
            resume(v, command)
    assert error.value.code == "source_acquisition_unavailable" and "credential" not in str(error.value)
    assert len(rows(v, Receipt)) == counts[Receipt]
    assert len(rows(v, SourceManifestRecord)) == counts[SourceManifestRecord]
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == head
    for model in (Result, SourceRevisionRecord, SourceInventoryRecord):
        assert len(rows(v, model)) == counts[model] + (kind == "manifest_committed")
    assert not acquire_events(command, f"system_image.source_acquisition.{kind}")
    calls = []
    original = SourceIngestionService.ingest
    def counted(connector, item):
        calls.append(item.id)
        return original(connector, item)
    monkeypatch.setattr(SourceIngestionService, "ingest", counted)
    resume(v, command)
    assert len(calls) == (kind == "result_recorded")
    assert len(acquire_events(command, "system_image.source_acquisition.result_recorded")) == 1
    assert len(acquire_events(command, "system_image.source_acquisition.manifest_committed")) == 1


def test_failed_source_outcome_is_not_retried_or_promoted_on_original_command(evidence_api, tmp_path, monkeypatch):
    v = evidence_api
    path, image, source = add_optional(v, tmp_path)
    path.unlink()
    command = running_command(v, selection(image, source["id"]), monkeypatch)
    resume(v, command)
    history = command_results(command)
    assert history[0]["status"] == "failed" and history[0]["content_ref"] is None
    assert str(tmp_path) not in str(history[0]["failure_reason"])
    path.write_text("# US-1\nA later explicit command may acquire this content.\n")
    calls = []
    original = SourceIngestionService.ingest
    def counted(connector, item):
        calls.append(item.id)
        return original(connector, item)
    monkeypatch.setattr(SourceIngestionService, "ingest", counted)
    resume(v, command)
    assert not calls and command_results(command) == history
    item = next(item for item in facts(v).raw_assets if item.id == source["id"])
    assert item.ingestion_status == "failed" and item.content_ref is None
    v["invoke"]("system_image.sources.ingest")
    assert source["id"] in calls and command_results(command) == history


def test_result_recovery_rechecks_live_source_permission(evidence_api, monkeypatch):
    v = evidence_api
    grant_tester(v)
    policy(v, (v["member"]["id"],))
    command = running_command(v, {}, monkeypatch, headers=v["member_headers"])
    service = fresh_service()
    with monkeypatch.context() as fault:
        fault.setattr(service._raw_asset_chunks, "materialize", lambda *args, **kwargs: (_ for _ in ()).throw(ProcessStopped()))
        with pytest.raises(ProcessStopped):
            resume(v, command, service=service, actor=v["member"])
    history, head = command_results(command), SourceSnapshotRepository().latest_manifest(v["project_id"])
    policy(v)
    before = facts(v)
    calls = []
    monkeypatch.setattr(SourceIngestionService, "ingest", lambda _self, source: calls.append(source.id))
    with pytest.raises(PlatformApplicationError) as error:
        resume(v, command, actor=v["member"])
    assert error.value.code == "source_access_denied"
    assert not calls and facts(v) == before and command_results(command) == history
    policy(v, (v["member"]["id"],))
    resume(v, command, actor=v["member"])
    assert not calls and command_results(command) == history
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == head


@pytest.mark.parametrize("table", ["source_acquisition_results", "source_acquisition_manifest_receipts"])
def test_command_result_history_is_immutable_and_cannot_be_downgraded(evidence_api, monkeypatch, table):
    v = evidence_api
    command = running_command(v, {}, monkeypatch)
    resume(v, command)
    for operation in (f"UPDATE {table} SET project_id = project_id", f"DELETE FROM {table}"):
        with pytest.raises(DBAPIError):
            with session_scope() as session:
                session.execute(text(f"{operation} WHERE invocation_id = :command"), {"command": command["id"]})
    import importlib
    migration = importlib.import_module("apps.api.migrations.versions.0095_source_acquisition_results")
    with session_scope() as session:
        with monkeypatch.context() as patch:
            patch.setattr(migration.op, "get_bind", lambda: session.connection())
            with pytest.raises(RuntimeError, match="populated"):
                migration.downgrade()


@pytest.mark.parametrize("fault", ["result_hash", "missing_result", "receipt_hash", "missing_receipt"])
def test_corrupt_or_missing_original_results_fail_closed_without_repair(evidence_api, monkeypatch, fault):
    v = evidence_api
    v["path"].write_text("class Recorded:\n    pass\n")
    command = running_command(v, {}, monkeypatch)
    resume(v, command)
    table = "source_acquisition_results" if fault in {"result_hash", "missing_result"} else "source_acquisition_manifest_receipts"
    with session_scope() as session:
        session.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER immutable_{table}"))
        if fault.startswith("missing"):
            session.execute(text(f"DELETE FROM {table} WHERE invocation_id = :command"), {"command": command["id"]})
        else:
            column = "result_hash" if fault == "result_hash" else "content_hash"
            session.execute(text(f"UPDATE {table} SET {column} = :digest WHERE invocation_id = :command"),
                {"command": command["id"], "digest": "sha256:" + "0" * 64})
        session.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER immutable_{table}"))
    history, head, before = command_results(command), SourceSnapshotRepository().latest_manifest(v["project_id"]), facts(v)
    events = acquire_events(command, "system_image.source_acquisition.manifest_committed")
    calls = []
    monkeypatch.setattr(SourceIngestionService, "ingest", lambda _self, source: calls.append(source.id))
    with pytest.raises(PlatformApplicationError):
        resume(v, command)
    assert not calls and command_results(command) == history and facts(v) == before
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == head
    assert acquire_events(command, "system_image.source_acquisition.manifest_committed") == events


@pytest.mark.parametrize("missing", ["result", "receipt"])
def test_missing_noop_history_is_not_recreated_after_sse_retention_cleanup(evidence_api, monkeypatch, missing):
    v = evidence_api
    origin = SourceSnapshotRepository().latest_manifest(v["project_id"])
    command = running_command(v, {}, monkeypatch)
    resume(v, command)
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == origin
    table = "source_acquisition_results" if missing == "result" else "source_acquisition_manifest_receipts"
    with session_scope() as session:
        session.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER immutable_{table}"))
        session.execute(text(f"DELETE FROM {table} WHERE invocation_id = :command"), {"command": command["id"]})
        session.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER immutable_{table}"))
        session.execute(text("DELETE FROM sse_event_outbox WHERE entity_id = :command"), {"command": command["id"]})
    before, results = facts(v), command_results(command)
    calls = []
    monkeypatch.setattr(SourceIngestionService, "ingest", lambda _self, source: calls.append(source.id))
    with pytest.raises(PlatformApplicationError) as error:
        resume(v, command)
    assert error.value.code == "source_acquisition_scope_invalid"
    assert not calls and command_results(command) == results and facts(v) == before
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == origin
    assert not acquire_events(command, "system_image.source_acquisition.manifest_committed")


def test_progress_identity_cannot_be_deleted_or_rebound(evidence_api, monkeypatch):
    v = evidence_api
    command = running_command(v, {}, monkeypatch)
    resume(v, command)
    for sql in ("DELETE FROM source_acquisition_progress", "UPDATE source_acquisition_progress SET intent_hash = 'wrong'"):
        with pytest.raises(DBAPIError):
            with session_scope() as session:
                session.execute(text(f"{sql} WHERE invocation_id = :command"), {"command": command["id"]})
    with session_scope() as session:
        progress = session.get(Progress, command["id"])
        assert progress.manifest_receipt_hash and len(progress.result_pins) == 1


def test_complete_result_replay_batch_loads_all_artifact_metadata(evidence_api, tmp_path, monkeypatch):
    v = evidence_api
    specs = []
    for index in range(11):
        path = tmp_path / f"requirement-{index}.md"
        path.write_text(f"# US-{index}\nOriginal requirement {index}.\n")
        specs.append({"source_type": "us_doc", "source_uri": str(path)})
    v["invoke"]("system_image.sources.register", {"source_specs": specs})
    command = running_command(v, {}, monkeypatch)
    resume(v, command)
    repository = SourceAcquisitionIntentRepository()
    intent, scope = repository.get(command["id"]), scope_for(v)
    queries = []

    def counted(_connection, _cursor, statement, _parameters, _context, _many):
        queries.append(" ".join(statement.lower().split()))

    event.listen(engine, "before_cursor_execute", counted)
    try:
        results = repository.results(intent, scope)
    finally:
        event.remove(engine, "before_cursor_execute", counted)
    assert len(results) == 12 and all(item.status == "captured" for item in results)
    for table in ("source_revisions", "source_acquisition_inventories"):
        assert sum(f"from {table} " in query for query in queries) <= 4, queries
    assert sum("from raw_assets " in query for query in queries) == 1, queries

    # A batched read must not skip the last item or trust a cached prior replay.
    last = results[-1]
    with session_scope() as session:
        session.execute(text("ALTER TABLE source_acquisition_inventories DISABLE TRIGGER immutable_source_acquisition_inventories"))
        session.execute(text("UPDATE source_acquisition_inventories SET report_hash = :hash WHERE inventory_id = :ident"),
            {"ident": last.inventory_id, "hash": "sha256:" + "0" * 64})
        session.execute(text("ALTER TABLE source_acquisition_inventories ENABLE TRIGGER immutable_source_acquisition_inventories"))
    with pytest.raises(ValueError, match="inventory changed"):
        repository.results(intent, scope)


def test_actual_exweb_archive_is_consumed_after_manifest_interruption_without_reacquisition(evidence_api, tmp_path, monkeypatch):
    root = os.getenv("EXWEB_SOURCE_REFRESH_GIT_ROOT")
    if not root:
        pytest.skip("explicit reviewed exweb Git export required")
    assert os.environ.get("NASUS_TEST_OBJECT_STORAGE_MODE") == "minio"
    from apps.api.tests.exweb_git_trees import AFTER, read_git_tree
    files, tree_hash, _ = read_git_tree(Path(root), AFTER)
    assert len(files) == 126
    exported = tmp_path / "fixed-exweb"
    exported.mkdir()
    for name, body in files:
        path = exported / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    v = evidence_api
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(exported)}]})
    image = read(v)
    source = next(item for item in image["sources"] if item["source_uri"] == str(exported))
    command = running_command(v, selection(image, source["id"]), monkeypatch)
    original = SourceAcquisitionIntentRepository.commit_manifest
    with monkeypatch.context() as fault:
        def stopped(repo, *args):
            original(repo, *args)
            raise ProcessStopped()
        fault.setattr(SourceAcquisitionIntentRepository, "commit_manifest", stopped)
        with pytest.raises(ProcessStopped):
            resume(v, command)
    saved = command_results(command)
    assert len(saved) == 1 and saved[0]["status"] == "captured"
    assert saved[0]["file_count"] == 126 and saved[0]["content_hash"] == tree_hash
    head = SourceSnapshotRepository().latest_manifest(v["project_id"])
    # These are controlled local changes, not a new upstream exweb revision.
    (exported / "README.md").write_bytes(b"Later mutable source must not replace the original archive.\n")
    (exported / "pom.xml").unlink()
    calls = []
    monkeypatch.setattr(SourceIngestionService, "ingest", lambda _self, source: calls.append(source.id))
    resume(v, command)
    assert not calls and command_results(command) == saved
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == head
    connector = SourceIngestionService()
    manifest = connector.snapshots.read_manifest(saved[0]["content_ref"], project_id=v["project_id"],
        source_id=source["id"], content_hash=tree_hash, max_files=5000, max_bytes=100 * 1024 * 1024,
        max_file_bytes=10 * 1024 * 1024)
    materialized = connector.snapshots.materialize(saved[0]["content_ref"], project_id=v["project_id"], source_id=source["id"],
        content_hash=tree_hash, max_files=5000, max_bytes=100 * 1024 * 1024, max_file_bytes=10 * 1024 * 1024)
    assert len(manifest["files"]) == 126
    assert all((materialized / name).read_bytes() == body for name, body in files)
    report = os.getenv("EXWEB_SOURCE_ACQUISITION_REPORT")
    if report:
        with Path(report).open("x") as output:
            json.dump({"schema": "nasus.exweb-source-acquisition-recovery.v1", "verified_at": datetime.now(timezone.utc).isoformat(),
                "commit": AFTER, "tree_hash": tree_hash, "file_count": 126, "postgres_private_minio": True,
                "original_running_canonical_command": True, "fresh_application_connector_repository": True,
                "simulated_interruption_after_manifest_commit": True, "reacquisition_count": len(calls),
                "exact_archive_file_bytes_verified": True, "independent_native_process_restart_verified": False,
                "temporal_lease_cancellation_verified": False, "external_model_or_target_execution_verified": False}, output, indent=2)
