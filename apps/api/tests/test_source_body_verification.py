from dataclasses import replace

import pytest

from apps.api.app.application.system_image.source_deltas import SourceBodyVerification, SourceRevisionReadTarget
from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.domain.system_image.source_access import StaleSourceAccessScope
from apps.api.app.domain.system_image.source_delta import SourceDeltaIntegrityError, SourceDeltaUnavailable, SourceRevisionPin
from apps.api.app.infrastructure.system_image.source_delta_archive import ArchivedSourceDeltaReader
from apps.api.tests.test_source_snapshot_archive import _ingestion


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    bodies = {"code.py": b"value = 1\n", "notes.txt": b"source-not-member-evidence\n", "empty.txt": b""}
    for path, body in bodies.items():
        (root / path).write_bytes(body)
    service = _ingestion(tmp_path)
    captured = service.ingest(RawAssetRecord(id="source", project_id="project", source_type="code", source_uri=str(root)))
    artifact = captured.snapshot
    pin = SourceRevisionPin("project", "binding", "revision", "code", artifact.external_revision,
                            artifact.manifest_hash, artifact.content_hash)
    target = SourceRevisionReadTarget(pin, "source", artifact.manifest_ref, artifact.policy_version,
                                    artifact.file_count, artifact.byte_count)
    reader = ArchivedSourceDeltaReader(service.snapshots.storage)
    snapshot = reader.read(target)
    for path in root.iterdir():
        path.unlink()
    root.rmdir()
    return reader, target, snapshot, bodies


@pytest.mark.parametrize("source_type", ["code", "us_doc", "test_asset"])
def test_every_raw_body_is_verified_without_workspace_or_materialized_cache(archive, source_type):
    reader, target, snapshot, bodies = archive
    target = replace(target, pin=replace(target.pin, source_type=source_type))
    snapshot = replace(snapshot, pin=target.pin)
    first = reader.verify_bodies(target, snapshot, require_current=lambda: None)
    second = reader.verify_bodies(target, snapshot, require_current=lambda: None)
    assert first == second and first.pin == target.pin
    assert first.verified_file_count == len(bodies)
    assert first.verified_byte_count == sum(map(len, bodies.values()))
    assert first.verification_hash.startswith("sha256:") and reader.archive.cache_dir is None


@pytest.mark.parametrize("failure", ["wrong_bytes", "wrong_size", "wrong_type", "offline"])
def test_unreferenced_file_corruption_or_storage_failure_is_not_a_complete_capture(archive, monkeypatch, failure):
    reader, target, snapshot, bodies = archive
    manifest = reader.archive.storage.get_json(target.manifest_ref)
    damaged = next(item["content_ref"] for item in manifest["files"] if item["path"] == "notes.txt")
    original = reader.archive.storage.get_bytes
    def read(ref, **kwargs):
        if ref != damaged:
            return original(ref, **kwargs)
        if failure == "offline":
            raise RuntimeError("private-endpoint:secret")
        if failure == "wrong_type":
            return "not-bytes"
        return b"!" * (len(bodies["notes.txt"]) if failure == "wrong_bytes" else 1)
    monkeypatch.setattr(reader.archive.storage, "get_bytes", read)
    assert reader.read(target) == snapshot
    error = SourceDeltaUnavailable if failure == "offline" else SourceDeltaIntegrityError
    with pytest.raises(error) as caught:
        reader.verify_bodies(target, snapshot, require_current=lambda: None)
    assert all(secret not in str(caught.value) for secret in ("notes.txt", "private-endpoint", "secret"))


@pytest.mark.parametrize("after_files", [0, 1, 3])
def test_access_revocation_stops_or_discards_body_verification(archive, monkeypatch, after_files):
    reader, target, snapshot, _ = archive
    calls = []
    original = reader.archive.storage.get_bytes
    def read(ref, **kwargs):
        body = original(ref, **kwargs)
        if "/files/" in ref:
            calls.append(ref)
        return body
    def authorized():
        if len(calls) >= after_files:
            raise StaleSourceAccessScope("revoked")
    monkeypatch.setattr(reader.archive.storage, "get_bytes", read)
    with pytest.raises(StaleSourceAccessScope):
        reader.verify_bodies(target, snapshot, require_current=authorized)
    assert len(calls) == after_files


def test_actual_file_hashes_do_not_replace_the_aggregate_capture_digest(archive):
    reader, target, _, bodies = archive
    bad = reader.archive.capture(project_id="project", source_id="source", files=sorted(bodies.items()),
        content_hash="sha256:" + "0" * 64, external_revision="bad-aggregate", excluded_directories=[])
    target = replace(target, pin=replace(target.pin, external_revision=bad.external_revision,
        manifest_hash=bad.manifest_hash, content_hash=bad.content_hash), manifest_ref=bad.manifest_ref,
        policy_version=bad.policy_version)
    with pytest.raises(SourceDeltaIntegrityError, match="captured source digest"):
        reader.verify_bodies(target, reader.read(target), require_current=lambda: None)


@pytest.mark.parametrize("change", [{"verified_file_count": True}, {"verified_file_count": 0},
    {"verified_byte_count": -1}, {"verified_byte_count": True}, {"verification_hash": "fake"}, {"method": "invented"}])
def test_verification_receipt_rejects_invented_counters_and_hashes(archive, change):
    _, target, _, _ = archive
    fields = {"pin": target.pin, "verified_file_count": 3, "verified_byte_count": target.byte_count,
              "verification_hash": "sha256:" + "1" * 64, **change}
    with pytest.raises(SourceDeltaIntegrityError):
        SourceBodyVerification(**fields)
