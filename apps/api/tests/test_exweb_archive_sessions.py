"""Actual fixed exweb bytes and private MinIO, not target business execution."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from time import perf_counter
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.api.app.application.system_image.raw_asset_chunks import SystemImageRawAssetChunkApplicationService
from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService


@pytest.mark.skipif(not os.getenv("EXWEB_CODE_CONTROL_SOURCE"), reason="explicit fixed exweb checkout required")
def test_exweb_archive_scopes_read_and_write_every_object_with_owned_clients(tmp_path, monkeypatch):
    assert os.environ.get("NASUS_TEST_OBJECT_STORAGE_MODE") == "minio"
    storage = ObjectStorage()
    assert storage.config.s3_enabled and storage.config.bucket.startswith("nasus-test-")
    root = Path(os.environ["EXWEB_CODE_CONTROL_SOURCE"]).resolve()
    sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    assert sha == "fe5827f6b76f77ef34918d8b452ee823142332dc"
    assert not subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
    clients = []
    factory = storage._create_s3_client

    class ObservedClient:
        def __init__(self, config):
            self.client, self.puts, self.gets, self.closed = factory(config), 0, 0, 0

        def put_object(self, **kwargs):
            self.puts += 1
            return self.client.put_object(**kwargs)

        def get_object(self, **kwargs):
            self.gets += 1
            return self.client.get_object(**kwargs)

        def close(self):
            self.closed += 1
            self.client.close()

    def create(config):
        client = ObservedClient(config)
        clients.append(client)
        return client
    monkeypatch.setattr(storage, "_create_s3_client", create)
    source = RawAssetRecord(id=f"exweb-{uuid4().hex}", project_id=f"archive-{uuid4().hex}", source_type="code", source_uri=str(root))
    service = SourceIngestionService(object_storage=storage, snapshot_cache_dir=tmp_path / "first")
    started = perf_counter()
    captured = service.ingest(source)
    capture_seconds = perf_counter() - started
    assert captured.file_count == 126 and captured.snapshot
    assert len(clients) == 2 and [client.puts for client in clients] == [1, 127]
    source = source.model_copy(update={"content_ref": captured.content_ref, "content_hash": captured.content_hash, "ingestion_status": "indexed"})
    started = perf_counter()
    units = service.extract_text_units(source)
    cold_read_seconds = perf_counter() - started
    assert len(units) == 126 and len(clients) == 3 and clients[2].gets == 127
    # A new materializer has no checkout or content cache from the first one.
    reopened = SourceIngestionService(object_storage=storage, snapshot_cache_dir=tmp_path / "reopened")
    replay = reopened.extract_text_units(source)
    assert [(unit.relative_path, unit.content_hash, unit.text) for unit in replay] == [
        (unit.relative_path, unit.content_hash, unit.text) for unit in units]
    assert len(clients) == 4 and clients[3].gets == 127
    published = []
    workspace = SimpleNamespace(artifact_write_session=storage.write_session,
        list_raw_assets=lambda _project: [source],
        put_json=lambda key, payload: storage.put_json(key, payload).storage_ref,
        replace_raw_asset_chunks=lambda _project, chunks: published.append(chunks))
    started = perf_counter()
    chunks = SystemImageRawAssetChunkApplicationService(workspace, service).materialize(
        source.project_id, captured_at="2026-10-08T00:00:00Z")
    chunk_seconds = perf_counter() - started
    assert published == [chunks] and len(clients) == 6 and clients[4].gets == 1 and clients[5].puts == len(chunks)
    assert all(client.closed == 1 for client in clients)
    with storage.read_session():
        for chunk in chunks:
            payload = storage.get_json(chunk.content_ref)
            assert payload["project_id"] == source.project_id and payload["raw_asset_id"] == source.id
            assert payload["relative_path"] == chunk.section_path and payload["content_hash"] == chunk.content_hash
            assert chunk.content_hash == "sha256:" + hashlib.sha256(payload["content"].encode()).hexdigest()
    assert len(clients) == 7 and clients[6].gets == len(chunks) and clients[6].closed == 1
    if os.getenv("EXWEB_ARCHIVE_SESSION_REPORT"):
        Path(os.environ["EXWEB_ARCHIVE_SESSION_REPORT"]).write_text(json.dumps({
            "repository": "https://github.com/kunben-duck/exweb.git", "revision": sha,
            "files": captured.file_count, "chunks": len(chunks), "source_hash": captured.content_hash,
            "snapshot_hash": captured.snapshot.manifest_hash, "capture_seconds": capture_seconds,
            "cold_read_seconds": cold_read_seconds, "chunk_seconds": chunk_seconds,
            "clients": [{"puts": client.puts, "gets": client.gets, "closed": client.closed} for client in clients],
            "real_minio": True, "target_repository_executed": False, "business_gold": False,
        }, indent=2) + "\n")
