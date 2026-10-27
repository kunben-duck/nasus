from __future__ import annotations

from dataclasses import replace
import errno
import hashlib
import os
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from apps.api.app.application.system_image.source_ports import SourceAcquisitionFailed
from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.domain.system_image.source_inventory import SourceInventory, SourceInventoryEntry
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.system_image import source_tree_scanner as scanner_module
from apps.api.app.infrastructure.system_image.source_tree_scanner import SourceTreeScanner
from apps.api.tests.test_source_snapshot_archive import _ingestion


def scanner(**limits):
    return SourceTreeScanner(**{
        "excluded_names": frozenset({".git", "build", "node_modules"}),
        "max_files": 100, "max_bytes": 10000, "max_file_bytes": 1000, **limits,
    })


def entries(scan):
    return {entry.path: entry for entry in scan.inventory.entries}


def test_inventory_records_pruned_boundaries_empty_directories_and_binary_raw_files(tmp_path):
    root = tmp_path / "build" / "repo"
    (root / "src").mkdir(parents=True)
    (root / "empty").mkdir()
    (root / "node_modules").mkdir()
    (root / "node_modules" / "ignored.txt").write_text("excluded")
    (root / "src" / "code.py").write_text("pass")
    (root / "binary.dat").write_bytes(b"a\0b")
    scan = scanner().scan(root)
    assert scan.inventory.complete and scan.inventory.enumeration_complete
    assert scan.inventory.file_count == 2 and scan.inventory.byte_count == 7
    assert set(entries(scan)) == {".", "src", "src/code.py", "empty", "node_modules", "binary.dat"}
    assert entries(scan)["node_modules"].status == "excluded"
    assert entries(scan)["empty"].status == "enumerated"
    assert entries(scan)["binary.dat"].status == "included"
    assert scan == scanner().scan(root)
    assert SourceInventory.from_payload(scan.inventory.to_payload()) == scan.inventory
    # The binding's ancestor named build is not an exclusion inside its scope.
    source = RawAssetRecord(id="source", project_id="project", source_type="code", source_uri=str(root))
    service = _ingestion(tmp_path)
    captured = service.ingest(source)
    restored = source.model_copy(update={"content_hash": captured.content_hash, "content_ref": captured.content_ref})
    assert [unit.relative_path for unit in service.extract_text_units(restored)] == ["src/code.py"]


def test_symlinks_and_special_files_are_reported_without_reading_targets(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    secret = tmp_path / "secret"
    secret.write_text("secret")
    (root / "link").symlink_to(secret)
    os.mkfifo(root / "pipe")
    original = scanner_module.os.open

    def guarded(name, flags, *args, **kwargs):
        assert name not in {"link", "pipe", str(secret)}
        return original(name, flags, *args, **kwargs)

    monkeypatch.setattr(scanner_module.os, "open", guarded)
    scan = scanner().scan(root)
    assert not scan.inventory.complete
    assert entries(scan)["link"].reason == "symbolic_link"
    assert entries(scan)["pipe"].reason == "special_file"
    assert scan.files == ()


def test_permission_failure_is_not_an_empty_or_deleted_subtree(tmp_path, monkeypatch):
    (tmp_path / "restricted").mkdir()
    (tmp_path / "safe.py").write_text("pass")
    original = scanner_module.os.open

    def denied(name, flags, *args, **kwargs):
        if name == "restricted":
            raise PermissionError(errno.EACCES, "private absolute path must not leak")
        return original(name, flags, *args, **kwargs)

    monkeypatch.setattr(scanner_module.os, "open", denied)
    scan = scanner().scan(tmp_path)
    assert not scan.inventory.complete and not scan.inventory.enumeration_complete
    assert entries(scan)["restricted"].reason == "permission_denied"
    assert entries(scan)["safe.py"].status == "included"
    assert "private absolute" not in str(scan.inventory.to_payload())


@pytest.mark.parametrize("limits,reason", [
    ({"max_files": 1}, "file_count_limit"),
    ({"max_file_bytes": 2}, "file_size_limit"),
    ({"max_bytes": 5}, "total_size_limit"),
    ({"max_entries": 2}, "inventory_entry_limit"),
])
def test_scan_limits_explicitly_fail_instead_of_silently_truncating(tmp_path, limits, reason):
    (tmp_path / "a.py").write_text("pass")
    (tmp_path / "b.py").write_text("pass")
    scan = scanner(**limits).scan(tmp_path)
    assert not scan.inventory.complete
    assert reason in {entry.reason for entry in scan.inventory.entries}
    assert len(scan.inventory.entries) <= limits.get("max_entries", 20000)
    if reason == "inventory_entry_limit":
        assert not scan.inventory.enumeration_complete


def test_file_changed_during_read_cannot_be_included(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("pass")
    original = scanner_module.os.read
    changed = False

    def mutating(fd, amount):
        nonlocal changed
        if not changed:
            changed = True
            (tmp_path / "a.py").write_text("fail")
        return original(fd, amount)

    monkeypatch.setattr(scanner_module.os, "read", mutating)
    scan = scanner().scan(tmp_path)
    assert not scan.inventory.complete
    assert entries(scan)["a.py"].reason == "source_changed"
    assert not scan.files


def test_directory_replaced_by_symlink_between_stat_and_open_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "inner").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("secret")
    original = scanner_module.os.open

    def replacing(name, flags, *args, **kwargs):
        if name == "inner":
            (root / "inner").rmdir()
            (root / "inner").symlink_to(outside, target_is_directory=True)
        return original(name, flags, *args, **kwargs)

    monkeypatch.setattr(scanner_module.os, "open", replacing)
    scan = scanner().scan(root)
    assert not scan.inventory.complete and not scan.inventory.enumeration_complete
    assert entries(scan)["inner"].status == "failed"
    assert not scan.files


def test_unsafe_path_has_explicit_failure_without_exposing_invalid_locator(tmp_path):
    (tmp_path / "evil\npath.py").write_text("pass")
    scan = scanner().scan(tmp_path)
    assert not scan.inventory.complete and not scan.inventory.enumeration_complete
    assert entries(scan)["."].reason == "unsafe_path"
    assert set(entries(scan)) == {"."}


def test_source_root_ancestor_symlink_is_not_followed(tmp_path):
    (tmp_path / "outside" / "repo").mkdir(parents=True)
    (tmp_path / "outside" / "repo" / "secret.py").write_text("secret")
    (tmp_path / "parent").symlink_to(tmp_path / "outside", target_is_directory=True)
    scan = scanner().scan(tmp_path / "parent" / "repo")
    assert not scan.inventory.complete and not scan.inventory.enumeration_complete
    assert not scan.files


def test_scandir_error_preserves_observed_entries_and_fails_enumeration(tmp_path, monkeypatch):
    (tmp_path / "first.py").write_text("pass")
    original = scanner_module.os.scandir

    class FailingScan:
        def __init__(self, fd):
            self.iterator = original(fd)

        def __enter__(self):
            return self

        def __iter__(self):
            yield next(self.iterator)
            raise OSError(errno.EIO, "scan failed")

        def __exit__(self, *args):
            self.iterator.close()

    monkeypatch.setattr(scanner_module.os, "scandir", FailingScan)
    scan = scanner().scan(tmp_path)
    assert not scan.inventory.complete and not scan.inventory.enumeration_complete
    assert entries(scan)["."].reason == "io_error"
    assert entries(scan)["first.py"].reason == "not_scanned"


def test_depth_limit_preserves_pruned_subtree_as_failure(tmp_path):
    (tmp_path / "one" / "two").mkdir(parents=True)
    (tmp_path / "one" / "two" / "hidden.py").write_text("pass")
    scan = scanner(max_depth=1).scan(tmp_path)
    assert not scan.inventory.complete and not scan.inventory.enumeration_complete
    assert entries(scan)["one/two"].reason == "depth_limit"


def test_failed_scan_is_archived_without_successful_source_snapshot(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "link").symlink_to(tmp_path / "nonexistent")
    service = _ingestion(tmp_path)
    source = RawAssetRecord(id="source", project_id="project", source_type="code", source_uri=str(root))
    with pytest.raises(SourceAcquisitionFailed) as caught:
        service.ingest(source)
    artifact = caught.value.inventory
    assert isinstance(caught.value, PermissionError)
    report = service.snapshots.storage.get_json(artifact.report_ref)
    assert snapshot_digest(report) == artifact.report_hash
    assert report["project_id"] == source.project_id and report["source_id"] == source.id
    assert artifact.status == "failed"
    assert SourceInventory.from_payload(report["inventory"]).complete is False
    assert not list((tmp_path / "objects").rglob("manifests/*.json"))


def test_v2_manifest_pins_inventory_and_rejects_rehashed_false_complete_report(tmp_path):
    path = tmp_path / "code.py"
    path.write_text("pass")
    service = _ingestion(tmp_path)
    source = RawAssetRecord(id="source", project_id="project", source_type="code", source_uri=str(path))
    result = service.ingest(source)
    manifest = service.snapshots.storage.get_json(result.content_ref)
    assert result.snapshot.policy_version == "nasus.source-snapshot.v2"
    assert manifest["inventory_hash"] == result.inventory.report_hash
    manifest["inventory"]["entries"][0]["content_hash"] = "sha256:" + "0" * 64
    digest = snapshot_digest(manifest)
    prefix = result.content_ref.split("/", 3)[3].rsplit("/", 1)[0]
    stored = service.snapshots.storage.put_json(f"{prefix}/{digest[7:]}.json", manifest)
    with pytest.raises(ValueError, match="inventory mismatch"):
        service.extract_text_units(source.model_copy(update={
            "content_ref": stored.storage_ref, "content_hash": result.content_hash,
        }))


def test_legacy_v1_snapshot_remains_replayable_without_inventing_inventory(tmp_path):
    service = _ingestion(tmp_path)
    digest = hashlib.sha256(b"old.py\0pass").hexdigest()
    snapshot = service.snapshots.capture(
        project_id="project", source_id="source", files=[("old.py", b"pass")],
        content_hash="sha256:" + digest, external_revision="old", excluded_directories=[],
    )
    assert snapshot.policy_version == "nasus.source-snapshot.v1"
    payload = service.snapshots.storage.get_json(snapshot.manifest_ref)
    assert "inventory" not in payload
    path = service.snapshots.materialize(
        snapshot.manifest_ref, project_id="project", source_id="source", content_hash=snapshot.content_hash,
        max_files=10, max_bytes=100, max_file_bytes=100,
    )
    assert (path / "old.py").read_bytes() == b"pass"


def test_inventory_domain_rejects_duplicate_or_falsely_included_entries(tmp_path):
    (tmp_path / "code.py").write_text("pass")
    inventory = scanner().scan(tmp_path).inventory
    with pytest.raises(ValueError, match="unique and sorted"):
        replace(inventory, entries=(*inventory.entries, inventory.entries[-1]))
    with pytest.raises(ValueError, match="digest"):
        SourceInventoryEntry("code.py", "file", "included", "raw_bytes_captured")
    assert not replace(inventory, enumeration_complete=False).complete


@pytest.mark.parametrize("failure", [OSError("storage unavailable"), ClientError({
    "Error": {"Code": "AccessDenied", "Message": "private bucket or endpoint"},
}, "PutObject")])
def test_snapshot_storage_failure_retains_scan_but_does_not_claim_a_snapshot(tmp_path, monkeypatch, failure):
    path = tmp_path / "code.py"
    path.write_text("pass")
    service = _ingestion(tmp_path)
    source = RawAssetRecord(id="source", project_id="project", source_type="code", source_uri=str(path))
    original = service.snapshots.storage.put_bytes

    def unavailable(key, body, *args, **kwargs):
        if "/files/" in key:
            raise failure
        return original(key, body, *args, **kwargs)

    monkeypatch.setattr(service.snapshots.storage, "put_bytes", unavailable)
    with pytest.raises(SourceAcquisitionFailed) as caught:
        service.ingest(source)
    # Scan completeness only attests to raw reads; a failed archive has no
    # SourceSnapshotArtifact/SourceRevision despite having a completed scan.
    assert caught.value.inventory.status == "complete"
    report = service.snapshots.storage.get_json(caught.value.inventory.report_ref)
    assert SourceInventory.from_payload(report["inventory"]).complete
    assert not list((tmp_path / "objects").rglob("manifests/*.json"))


def test_report_storage_failure_does_not_fabricate_durable_inventory(tmp_path, monkeypatch):
    path = tmp_path / "code.py"
    path.write_text("pass")
    service = _ingestion(tmp_path)

    def denied(*args, **kwargs):
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "private endpoint"}}, "PutObject")

    monkeypatch.setattr(service.snapshots.storage, "put_json", denied)
    with pytest.raises(RuntimeError, match="source archive storage write failed") as caught:
        service.ingest(RawAssetRecord(id="source", project_id="project", source_type="code", source_uri=str(path)))
    assert "private endpoint" not in str(caught.value)
    assert not isinstance(caught.value, SourceAcquisitionFailed)


def test_missing_root_has_failed_inventory_not_a_successful_empty_snapshot(tmp_path):
    scan = scanner().scan(tmp_path / "missing")
    assert not scan.inventory.complete and not scan.inventory.enumeration_complete
    assert entries(scan)["."].reason == "source_changed"
