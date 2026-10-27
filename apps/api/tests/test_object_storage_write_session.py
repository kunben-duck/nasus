"""Batch transport lifetimes are not content caches or write authorization."""
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from threading import Barrier, Event

import pytest

from apps.api.app.application.system_image.raw_asset_chunks import SystemImageRawAssetChunkApplicationService
from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService


@pytest.fixture
def transport(tmp_path, monkeypatch):
    storage = ObjectStorage(ObjectStorageConfig("http://127.0.0.1:1", "test", "key", "secret", "local", tmp_path / "objects"))
    clients, objects, bodies = [], {}, []

    class Client:
        def __init__(self):
            self.closed, self.writes, self.reads = 0, [], []

        def put_object(self, **kwargs):
            self.writes.append(kwargs)
            objects[kwargs["Key"]] = kwargs["Body"]

        def get_object(self, **kwargs):
            self.reads.append(kwargs)
            value = objects[kwargs["Key"]]
            body = BytesIO(value)
            bodies.append(body)
            return {"ContentLength": len(value), "Body": body}

        def close(self):
            self.closed += 1

    def create(_config):
        client = Client()
        clients.append(client)
        return client

    monkeypatch.setattr(storage, "_create_s3_client", create)
    return storage, clients, objects, bodies


def test_nested_write_sessions_reuse_only_their_owned_transport(transport):
    storage, clients, objects, _ = transport
    with storage.write_session():
        first = storage.put_bytes("same", b"first")
        with storage.write_session():
            second = storage.put_bytes("same", b"second")
        assert first.content_hash != second.content_hash and objects["same"] == b"second"
        assert len(clients) == 1 and len(clients[0].writes) == 2 and clients[0].closed == 0
        copied = copy_context()
    assert clients[0].closed == 1
    with pytest.raises(RuntimeError, match="closed"):
        copied.run(storage.put_bytes, "outside", b"no")
    storage.put_bytes("outside", b"new")
    assert len(clients) == 2 and clients[1].closed == 1 and "outside" in objects


def test_write_and_read_scopes_never_share_credentials_or_transport(transport):
    storage, clients, _, bodies = transport
    with storage.write_session():
        result = storage.put_bytes("value", b"first")
        with storage.read_session():
            assert storage.get_bytes(result.storage_ref) == b"first"
            storage.put_bytes("value", b"second")
            assert storage.get_bytes(result.storage_ref) == b"second"
            assert len(clients) == 2 and all(client.closed == 0 for client in clients)
        assert clients[0].closed == 0 and clients[1].closed == 1
    assert clients[0].closed == 1 and all(body.closed for body in bodies)


@pytest.mark.parametrize("failure", [LookupError, KeyboardInterrupt])
def test_write_failure_and_cancellation_release_scope_without_implicit_retry(transport, failure):
    storage, clients, _, _ = transport
    with pytest.raises(failure):
        with storage.write_session():
            storage.put_bytes("first", b"first")
            def fail(**_kwargs):
                raise failure("write failed")
            clients[0].put_object = fail
            storage.put_bytes("second", b"second")
    assert len(clients) == 1 and clients[0].closed == 1 and storage._write_clients.get() is None
    storage.put_bytes("fresh", b"fresh")
    assert len(clients) == 2 and clients[1].closed == 1


def test_write_config_change_fails_closed_and_nested_scope_restores_original(transport):
    storage, clients, _, _ = transport
    original = storage.config
    with storage.write_session():
        storage.put_bytes("first", b"first")
        storage.config = replace(original, secret_key="changed")
        with pytest.raises(RuntimeError, match="configuration changed"):
            storage.put_bytes("forbidden", b"no")
        with storage.write_session():
            storage.put_bytes("nested", b"changed")
        storage.config = original
        storage.put_bytes("last", b"last")
    assert len(clients) == 2 and all(client.closed == 1 for client in clients)
    assert [len(client.writes) for client in clients] == [2, 1]


def test_unused_and_local_write_sessions_do_not_construct_clients(transport):
    storage, clients, _, _ = transport
    with storage.write_session():
        pass
    storage.config = replace(storage.config, endpoint=None)
    with storage.write_session():
        stored = storage.put_bytes("local", b"local")
    assert stored.backend == "local" and storage.get_bytes(stored.storage_ref) == b"local" and not clients


def test_independent_threads_have_independent_write_scopes(transport):
    storage, clients, _, _ = transport
    barrier = Barrier(2)
    def write(index):
        with storage.write_session():
            barrier.wait(timeout=5)
            storage.put_bytes(f"thread-{index}", b"value")
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(write, index) for index in range(2)]
        for future in futures:
            future.result(timeout=5)
    assert len(clients) == 2 and all(client.closed == len(client.writes) == 1 for client in clients)


def test_inherited_process_write_scope_is_rejected_without_acquiring_its_lock(transport):
    storage, clients, _, _ = transport
    with storage.write_session():
        storage.put_bytes("first", b"first")
        scope = storage._write_clients.get()
        original_pid = scope.pid
        scope.pid = -1
        try:
            with scope._lock:
                with pytest.raises(RuntimeError, match="process"):
                    storage.put_bytes("forbidden", b"no")
                with storage.write_session():
                    storage.put_bytes("fresh", b"fresh")
        finally:
            scope.pid = original_pid
    assert len(clients) == 2 and all(client.closed == len(client.writes) == 1 for client in clients)


def test_scope_exit_waits_for_the_last_active_inherited_write(transport):
    storage, clients, _, _ = transport
    started, release = Event(), Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with storage.write_session():
            storage.put_bytes("first", b"first")
            copied = copy_context()
            original = clients[0].put_object
            def blocked(**kwargs):
                started.set()
                assert release.wait(timeout=5)
                original(**kwargs)
            clients[0].put_object = blocked
            pending = executor.submit(copied.run, storage.put_bytes, "inherited", b"value")
            assert started.wait(timeout=5)
        try:
            assert clients[0].closed == 0
        finally:
            release.set()
        assert pending.result(timeout=5).backend == "s3"
    assert clients[0].closed == 1 and len(clients[0].writes) == 2


@pytest.mark.parametrize("caller_fails", [False, True])
def test_close_failure_restores_write_scope_and_preserves_the_original_error(transport, caller_fails):
    storage, clients, _, _ = transport
    def close():
        clients[0].closed += 1
        raise OSError("close failed")
    expected, message = (LookupError, "caller failed") if caller_fails else (OSError, "close failed")
    with pytest.raises(expected, match=message):
        with storage.write_session():
            storage.put_bytes("first", b"first")
            clients[0].close = close
            if caller_fails:
                raise LookupError("caller failed")
    assert storage._write_clients.get() is None and clients[0].closed == 1
    storage.put_bytes("fresh", b"fresh")
    assert clients[1].closed == 1


def test_snapshot_capture_and_materialization_reuse_connections_without_skipping_objects(transport, tmp_path):
    storage, clients, objects, bodies = transport
    root = tmp_path / "repo"
    root.mkdir()
    for index in range(16):
        (root / f"file{index}.py").write_text(f"VALUE = {index}\n")
    service = SourceIngestionService(object_storage=storage, snapshot_cache_dir=tmp_path / "snapshots")
    source = RawAssetRecord(id="source", project_id="project", source_type="code", source_uri=str(root))
    ingested = service.ingest(source)
    # One inventory operation and one complete snapshot write operation.
    assert len(clients) == 2 and [len(client.writes) for client in clients] == [1, 17]
    assert ingested.file_count == 16 and len(objects) == 18 and all(client.closed == 1 for client in clients)
    source = source.model_copy(update={"content_ref": ingested.content_ref, "content_hash": ingested.content_hash})
    units = service.extract_text_units(source)
    assert len(clients) == 3 and len(clients[2].reads) == 17 and clients[2].closed == 1
    assert len(units) == 16 and all(body.closed for body in bodies)
    (Path(units[0].source_root) / units[0].relative_path).write_text("corrupt\n")
    with pytest.raises(ValueError, match="file hash mismatch"):
        service.extract_text_units(source)
    assert clients[-1].closed == 1


def test_chunk_materialization_uses_one_write_scope_and_publishes_only_complete_result(transport):
    storage, clients, objects, _ = transport
    source = RawAssetRecord(id="source", project_id="project", source_type="code", source_uri="fixture", ingestion_status="indexed")
    published = []
    workspace = SimpleNamespace(
        artifact_write_session=storage.write_session,
        list_raw_assets=lambda _project: [source],
        put_json=lambda key, payload: storage.put_json(key, payload).storage_ref,
        replace_raw_asset_chunks=lambda _project, chunks: published.append(chunks),
    )
    units = [SimpleNamespace(text=f"VALUE = {index}\n", relative_path=f"file{index}.py", content_hash=f"hash{index}", byte_count=10)
             for index in range(16)]
    service = SystemImageRawAssetChunkApplicationService(workspace, SimpleNamespace(extract_text_units=lambda _source: units))
    result = service.materialize("project", captured_at="2026-10-08T00:00:00Z")
    assert len(clients) == 1 and len(clients[0].writes) == len(objects) == len(result) == 16
    assert clients[0].closed == 1 and published == [result]

    original = storage._create_s3_client
    def create(config):
        client = original(config)
        put = client.put_object
        def fail_on_second(**kwargs):
            if client.writes:
                raise LookupError("second write failed")
            put(**kwargs)
        client.put_object = fail_on_second
        return client
    storage._create_s3_client = create
    with pytest.raises(LookupError, match="second write failed"):
        service.materialize("project", captured_at="2026-10-08T00:00:00Z")
    assert clients[-1].closed == 1 and published == [result]
