from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from ...domain.system_image.source_snapshots import SourceSnapshotArtifact, snapshot_digest
from ...domain.system_image.evidence import valid_digest
from ...domain.system_image.source_inventory import SourceInventory, SourceInventoryArtifact
from ..storage.object_storage import ObjectStorage


class SourceSnapshotArchive:
    """Immutable, content-addressed raw files; local checkouts are rebuildable."""

    schema_version = "nasus.source-snapshot.v2"
    legacy_schema_version = "nasus.source-snapshot.v1"
    prefix = "system-image/source-snapshots/"

    def __init__(self, storage: ObjectStorage, cache_dir: Path | None = None) -> None:
        self.storage = storage
        self.cache_dir = cache_dir

    def _store(self, key: str, payload: bytes | dict):
        try:
            return self.storage.put_json(key, payload) if isinstance(payload, dict) else self.storage.put_bytes(key, payload)
        except Exception as exc:
            # SDK-specific exceptions must not bypass the application failure
            # path or expose credentials/endpoints in a source failure reason.
            raise RuntimeError("source archive storage write failed") from exc

    @staticmethod
    def _path(value: str) -> str:
        path = PurePosixPath(value)
        if (
            not path.parts or path.is_absolute() or ".." in path.parts
            or "\\" in value or any(ord(char) < 32 for char in value) or value != path.as_posix()
        ):
            raise ValueError("unsafe source snapshot path")
        return value

    def capture(
        self, *, project_id: str, source_id: str, files: list[tuple[str, bytes]],
        content_hash: str, external_revision: str | None, excluded_directories: list[str],
        inventory: SourceInventory | None = None,
    ) -> SourceSnapshotArtifact:
        with self.storage.write_session():
            return self._capture(project_id=project_id, source_id=source_id, files=files,
                content_hash=content_hash, external_revision=external_revision,
                excluded_directories=excluded_directories, inventory=inventory)

    def _capture(
        self, *, project_id: str, source_id: str, files: list[tuple[str, bytes]],
        content_hash: str, external_revision: str | None, excluded_directories: list[str],
        inventory: SourceInventory | None = None,
    ) -> SourceSnapshotArtifact:
        if inventory is not None:
            expected = {item.path: (item.byte_count, item.content_hash) for item in inventory.entries if item.status == "included"}
            actual = {path: (len(body), "sha256:" + hashlib.sha256(body).hexdigest()) for path, body in files}
            if (not inventory.complete or expected != actual or len(actual) != len(files)
                    or tuple(sorted(excluded_directories)) != inventory.excluded_names):
                raise ValueError("source snapshot inventory mismatch")
        namespace = hashlib.sha256(f"{project_id}\0{source_id}".encode()).hexdigest()
        key_prefix = f"{self.prefix}{namespace}"
        entries: list[dict[str, Any]] = []
        for relative_path, body in files:
            relative_path = self._path(relative_path)
            digest = hashlib.sha256(body).hexdigest()
            stored = self._store(f"{key_prefix}/files/{digest}", body)
            if stored.content_hash != f"sha256:{digest}":
                raise RuntimeError("source snapshot storage digest mismatch")
            entries.append({
                "path": relative_path, "content_hash": stored.content_hash,
                "content_ref": stored.storage_ref, "byte_count": len(body),
            })
        payload = {
            "schema_version": self.schema_version if inventory is not None else self.legacy_schema_version,
            "project_id": project_id, "source_id": source_id,
            "external_revision": external_revision or content_hash,
            "content_hash": content_hash, "files": entries,
            "scope": {"excluded_directories": sorted(excluded_directories)},
        }
        if inventory is not None:
            payload["inventory"] = inventory.to_payload()
            payload["inventory_hash"] = snapshot_digest({
                "project_id": project_id, "source_id": source_id,
                "external_revision": external_revision or content_hash, "inventory": inventory.to_payload(),
            })
        digest = snapshot_digest(payload)
        stored = self._store(f"{key_prefix}/manifests/{digest[7:]}.json", payload)
        if stored.content_hash != digest:
            raise RuntimeError("source manifest storage digest mismatch")
        return SourceSnapshotArtifact(
            external_revision=external_revision or content_hash,
            content_hash=content_hash, manifest_hash=digest, manifest_ref=stored.storage_ref,
            file_count=len(entries), byte_count=sum(item["byte_count"] for item in entries),
            policy_version=payload["schema_version"],
        )

    def store_inventory(
        self, inventory: SourceInventory, *, project_id: str, source_id: str,
        external_revision: str | None,
    ) -> SourceInventoryArtifact:
        namespace = hashlib.sha256(f"{project_id}\0{source_id}".encode()).hexdigest()
        payload = {"project_id": project_id, "source_id": source_id,
                   "external_revision": external_revision, "inventory": inventory.to_payload()}
        digest = snapshot_digest(payload)
        stored = self._store(f"{self.prefix}{namespace}/inventories/{digest[7:]}.json", payload)
        if stored.content_hash != digest:
            raise RuntimeError("source inventory storage digest mismatch")
        return SourceInventoryArtifact(
            project_id, source_id, digest, stored.storage_ref,
            "complete" if inventory.complete else "failed", inventory.enumeration_complete,
            inventory.file_count, inventory.byte_count, len(inventory.entries),
        )

    def owns_ref(self, ref: str | None) -> bool:
        return bool(ref and ref.startswith(("s3://", "local-object://")) and f"/{self.prefix}" in ref)

    def read_manifest(
        self, ref: str, *, project_id: str, source_id: str, content_hash: str,
        max_files: int, max_bytes: int, max_file_bytes: int,
        manifest_hash: str | None = None,
    ) -> dict[str, Any]:
        namespace = hashlib.sha256(f"{project_id}\0{source_id}".encode()).hexdigest()
        scheme = "s3" if self.storage.config.s3_enabled else "local-object"
        prefix = f"{scheme}://{self.storage.config.bucket}/{self.prefix}{namespace}"
        if not ref.startswith(prefix + "/manifests/"):
            raise ValueError("source snapshot manifest scope mismatch")
        body = self.storage.get_bytes(ref, max_bytes=32 * 1024 * 1024)
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("source snapshot manifest is invalid")
        digest = snapshot_digest(payload)
        if ref != f"{prefix}/manifests/{digest[7:]}.json" or (manifest_hash is not None and manifest_hash != digest):
            raise ValueError("source snapshot manifest hash mismatch")
        if (
            payload.get("schema_version") not in {self.schema_version, self.legacy_schema_version}
            or payload.get("project_id") != project_id or payload.get("source_id") != source_id
            or payload.get("content_hash") != content_hash
            or not isinstance(payload.get("external_revision"), str) or not payload["external_revision"]
        ):
            raise ValueError("source snapshot scope mismatch")
        entries = payload.get("files")
        if not isinstance(entries, list) or not entries or len(entries) > max_files:
            raise ValueError("source snapshot file count is invalid")
        if any(not isinstance(item, dict) or not isinstance(item.get("path"), str) for item in entries):
            raise ValueError("invalid source snapshot file entry")
        paths = [self._path(item["path"]) for item in entries]
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate source snapshot path")
        if any(type(item.get("byte_count")) is not int or not 0 <= item["byte_count"] <= max_file_bytes for item in entries):
            raise ValueError("source snapshot file size is invalid")
        if sum(item["byte_count"] for item in entries) > max_bytes:
            raise ValueError("source snapshot exceeds byte limit")
        for item in entries:
            if not isinstance(item.get("content_hash"), str) or not valid_digest(item["content_hash"]):
                raise ValueError("source snapshot file digest is invalid")
            if item.get("content_ref") != f"{prefix}/files/{item['content_hash'][7:]}":
                raise ValueError("source snapshot object scope mismatch")
        if payload["schema_version"] == self.schema_version:
            inventory = SourceInventory.from_payload(payload.get("inventory"))
            expected = {item.path: (item.byte_count, item.content_hash) for item in inventory.entries if item.status == "included"}
            actual = {item["path"]: (item["byte_count"], item["content_hash"]) for item in entries}
            inventory_hash = snapshot_digest({
                "project_id": project_id, "source_id": source_id,
                "external_revision": payload["external_revision"], "inventory": inventory.to_payload(),
            })
            if (not inventory.complete or expected != actual or inventory_hash != payload.get("inventory_hash")
                    or payload.get("scope") != {"excluded_directories": list(inventory.excluded_names)}):
                raise ValueError("source snapshot inventory mismatch")
        return payload

    def verified_files(self, ref, *, project_id, source_id, content_hash, manifest_hash,
                       max_files, max_bytes, max_file_bytes):
        with self.storage.read_session():
            payload = self.read_manifest(ref, project_id=project_id, source_id=source_id,
                content_hash=content_hash, manifest_hash=manifest_hash, max_files=max_files,
                max_bytes=max_bytes, max_file_bytes=max_file_bytes)
            files, digest = [], hashlib.sha256()
            for entry in payload["files"]:
                body = self.storage.get_bytes(entry["content_ref"], max_bytes=max_file_bytes)
                if len(body) != entry["byte_count"] or "sha256:" + hashlib.sha256(body).hexdigest() != entry["content_hash"]:
                    raise ValueError("source snapshot file hash mismatch")
                digest.update(entry["path"].encode())
                digest.update(b"\0")
                digest.update(body)
                files.append((entry["path"], body))
            if "sha256:" + digest.hexdigest() != content_hash:
                raise ValueError("source snapshot content hash mismatch")
            return payload, tuple(files)

    def materialize(
        self, ref: str, *, project_id: str, source_id: str, content_hash: str,
        max_files: int, max_bytes: int, max_file_bytes: int,
    ) -> Path:
        with self.storage.read_session():
            return self._materialize(ref, project_id=project_id, source_id=source_id,
                content_hash=content_hash, max_files=max_files, max_bytes=max_bytes,
                max_file_bytes=max_file_bytes)

    def _materialize(
        self, ref: str, *, project_id: str, source_id: str, content_hash: str,
        max_files: int, max_bytes: int, max_file_bytes: int,
    ) -> Path:
        if self.cache_dir is None:
            raise RuntimeError("snapshot materialization requires a cache directory")
        payload = self.read_manifest(ref, project_id=project_id, source_id=source_id,
                                     content_hash=content_hash, max_files=max_files,
                                     max_bytes=max_bytes, max_file_bytes=max_file_bytes)
        entries = payload["files"]
        digest = snapshot_digest(payload)
        namespace = hashlib.sha256(f"{project_id}\0{source_id}".encode()).hexdigest()
        parent = self.cache_dir / namespace
        parent.mkdir(parents=True, exist_ok=True)
        destination = parent / digest[7:]
        if destination.exists():
            self._validate_checkout(destination, entries, content_hash)
            return destination
        temporary = Path(tempfile.mkdtemp(prefix=".capture-", dir=parent))
        try:
            for entry in entries:
                body = self.storage.get_bytes(entry["content_ref"], max_bytes=max_file_bytes)
                target = temporary / entry["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
            self._validate_checkout(temporary, entries, content_hash)
            try:
                os.rename(temporary, destination)
            except OSError:
                if not destination.is_dir():
                    raise
                self._validate_checkout(destination, entries, content_hash)
            return destination
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    @staticmethod
    def _validate_checkout(root: Path, entries: list[dict[str, Any]], expected_hash: str) -> None:
        if root.is_symlink():
            raise ValueError("source snapshot checkout is a symlink")
        actual_paths = set()
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ValueError("source snapshot contains a symlink")
            if path.is_file():
                actual_paths.add(path.relative_to(root).as_posix())
        if actual_paths != {item["path"] for item in entries}:
            raise ValueError("source snapshot inventory mismatch")
        digest = hashlib.sha256()
        for entry in entries:
            body = (root / entry["path"]).read_bytes()
            if len(body) != entry["byte_count"] or "sha256:" + hashlib.sha256(body).hexdigest() != entry["content_hash"]:
                raise ValueError("source snapshot file hash mismatch")
            digest.update(entry["path"].encode())
            digest.update(b"\0")
            digest.update(body)
        if f"sha256:{digest.hexdigest()}" != expected_hash:
            raise ValueError("source snapshot content hash mismatch")
