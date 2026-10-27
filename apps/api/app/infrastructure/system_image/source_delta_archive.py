from dataclasses import asdict
import hashlib

from ...application.system_image.source_deltas import SourceBodyVerification
from ...domain.system_image.source_delta import (
    SourceDeltaIntegrityError, SourceDeltaSnapshot, SourceDeltaUnavailable,
)
from ...domain.system_image.source_inventory import SourceInventory, SourceInventoryEntry
from ...domain.system_image.source_snapshots import snapshot_digest
from .source_snapshot_archive import SourceSnapshotArchive


class ArchivedSourceDeltaReader:
    def __init__(self, storage, *, max_files=5000, max_bytes=100 * 1024 * 1024,
                 max_file_bytes=10 * 1024 * 1024):
        self.archive = SourceSnapshotArchive(storage)
        self.max_files, self.max_bytes, self.max_file_bytes = max_files, max_bytes, max_file_bytes

    def read(self, target):
        try:
            pin = target.pin
            payload = self.archive.read_manifest(target.manifest_ref, project_id=pin.project_id,
                source_id=target.source_id, content_hash=pin.content_hash, manifest_hash=pin.manifest_hash,
                max_files=self.max_files, max_bytes=self.max_bytes, max_file_bytes=self.max_file_bytes)
            if (payload["external_revision"] != pin.external_revision
                    or payload["schema_version"] != target.policy_version
                    or len(payload["files"]) != target.file_count
                    or sum(item["byte_count"] for item in payload["files"]) != target.byte_count):
                raise SourceDeltaIntegrityError("archive differs from the stored source revision")
            files = tuple(sorted((SourceInventoryEntry(item["path"], "file", "included", "captured",
                item["byte_count"], item["content_hash"]) for item in payload["files"]), key=lambda item: item.path))
            inventory = SourceInventory.from_payload(payload["inventory"]) if "inventory" in payload else None
            if inventory is not None:
                files = tuple(item for item in inventory.entries if item.status == "included")
            return SourceDeltaSnapshot(pin, files, tuple(payload["scope"]["excluded_directories"]), inventory)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise SourceDeltaIntegrityError("source delta archive failed integrity verification") from exc
        except Exception as exc:
            raise SourceDeltaUnavailable("source delta archive is unavailable") from exc

    def verify_bodies(self, target, expected, *, require_current):
        require_current()
        if self.read(target) != expected:
            raise SourceDeltaIntegrityError("source inventory changed during body verification")
        try:
            payload = self.archive.read_manifest(target.manifest_ref, project_id=target.pin.project_id,
                source_id=target.source_id, content_hash=target.pin.content_hash, manifest_hash=target.pin.manifest_hash,
                max_files=self.max_files, max_bytes=self.max_bytes, max_file_bytes=self.max_file_bytes)
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceDeltaIntegrityError("source body manifest failed integrity verification") from exc
        except Exception as exc:
            raise SourceDeltaUnavailable("source body archive is unavailable") from exc
        digest, count = hashlib.sha256(), 0
        for entry in payload["files"]:
            require_current()
            try:
                body = self.archive.storage.get_bytes(entry["content_ref"], max_bytes=self.max_file_bytes)
            except Exception as exc:
                raise SourceDeltaUnavailable("source body archive is unavailable") from exc
            if (not isinstance(body, bytes) or len(body) != entry["byte_count"]
                    or "sha256:" + hashlib.sha256(body).hexdigest() != entry["content_hash"]):
                raise SourceDeltaIntegrityError("source body differs from its immutable manifest")
            digest.update(entry["path"].encode("utf-8"))
            digest.update(b"\0")
            digest.update(body)
            count += len(body)
        require_current()
        if "sha256:" + digest.hexdigest() != target.pin.content_hash:
            raise SourceDeltaIntegrityError("source bodies differ from the captured source digest")
        verification_hash = snapshot_digest({"method": "nasus.source-body-verification.v1",
            "pin": asdict(target.pin), "verified_file_count": len(payload["files"]), "verified_byte_count": count})
        return SourceBodyVerification(target.pin, len(payload["files"]), count, verification_hash)
