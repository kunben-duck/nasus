from __future__ import annotations

import hashlib
from contextlib import contextmanager
from contextvars import ContextVar

from ...application.system_image.evidence_queries import EvidenceReadTarget
from ...application.operation_read_scope import OperationReadScope
from ...domain.system_image.evidence import EvidenceIntegrityError, EvidenceUnavailableError
from ..storage.object_storage import ObjectStorage
from .source_snapshot_archive import SourceSnapshotArchive


class ArchivedEvidenceSourceReader:
    def __init__(self, storage: ObjectStorage, *, max_files: int = 5000,
                 max_bytes: int = 100 * 1024 * 1024, max_file_bytes: int = 10 * 1024 * 1024) -> None:
        self.storage = storage
        self.archive = SourceSnapshotArchive(storage)
        self.max_files, self.max_bytes, self.max_file_bytes = max_files, max_bytes, max_file_bytes
        self._manifests = ContextVar("evidence_verified_manifests", default=None)
        self._manifest_scope = ContextVar("evidence_verified_manifest_scope", default=None)

    @contextmanager
    def verified_read_session(self):
        # Only immutable, hash-verified manifests are reused. Raw files and live
        # permissions are rechecked by every evidence read.
        scope = OperationReadScope({})
        token = self._manifests.set(scope.value)
        scope_token = self._manifest_scope.set(scope)
        try:
            with self.storage.read_session():
                yield
        finally:
            scope.close()
            self._manifest_scope.reset(scope_token)
            self._manifests.reset(token)

    def read(self, target: EvidenceReadTarget) -> bytes:
        evidence = target.evidence
        try:
            key = (evidence.project_id, target.source_id, target.manifest_ref,
                   target.source_content_hash, target.manifest_hash,
                   self.max_files, self.max_bytes, self.max_file_bytes)
            scope = self._manifest_scope.get()
            cache = scope.value if scope is not None and scope.is_current else None
            entries = cache.get(key) if cache is not None else None
            if entries is None:
                manifest = self.archive.read_manifest(
                    target.manifest_ref, project_id=evidence.project_id, source_id=target.source_id,
                    content_hash=target.source_content_hash, manifest_hash=target.manifest_hash,
                    max_files=self.max_files, max_bytes=self.max_bytes, max_file_bytes=self.max_file_bytes,
                )
                entries = {item["path"]: item for item in manifest["files"]}
                if cache is not None:
                    if len(cache) >= 4:
                        del cache[next(iter(cache))]
                    cache[key] = entries
            entry = entries.get(evidence.locator.relative_path)
            if entry is None or entry["content_hash"] != evidence.file_hash or entry["content_ref"] != evidence.object_ref:
                raise EvidenceIntegrityError("evidence does not match its pinned source manifest")
            body = self.storage.get_bytes(entry["content_ref"], max_bytes=self.max_file_bytes)
            if len(body) != entry["byte_count"] or "sha256:" + hashlib.sha256(body).hexdigest() != evidence.file_hash:
                raise EvidenceIntegrityError("evidence raw file digest mismatch")
            return body
        except (ValueError, KeyError, TypeError) as exc:
            raise EvidenceIntegrityError("evidence archive validation failed") from exc
        except EvidenceIntegrityError:
            raise
        except Exception as exc:
            raise EvidenceUnavailableError("evidence archive is unavailable") from exc
