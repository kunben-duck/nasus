from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator
from zipfile import BadZipFile, ZipFile

import fcntl

from ...application.system_image.source_ports import MaterializedSource
from ...application.system_image.system_image_models import RawAssetRecord
from ..storage import ObjectStorage


class ObjectStorageSourceConnectorError(OSError):
    """Raised when a managed document/test bundle cannot be materialized safely."""


class ObjectStorageSourceConnector:
    connector_kind = "object-storage-bundle"

    def __init__(
        self,
        object_storage: ObjectStorage,
        *,
        cache_dir: Path | None = None,
        max_archive_bytes: int | None = None,
        max_files: int | None = None,
        max_extracted_bytes: int | None = None,
    ) -> None:
        self._object_storage = object_storage
        self.cache_dir = (
            cache_dir or Path(os.getenv("NASUS_SOURCE_CACHE_DIR", ".nasus/source-cache")) / "objects"
        ).expanduser().resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_archive_bytes = max_archive_bytes or self._env_int(
            "NASUS_SOURCE_UPLOAD_MAX_ARCHIVE_BYTES",
            60 * 1024 * 1024,
        )
        self.max_files = max_files or self._env_int("NASUS_SOURCE_UPLOAD_MAX_FILES", 100)
        self.max_extracted_bytes = max_extracted_bytes or self._env_int(
            "NASUS_SOURCE_UPLOAD_MAX_BYTES",
            50 * 1024 * 1024,
        )

    def supports(self, source: RawAssetRecord) -> bool:
        return source.source_type in {"us_doc", "test_asset"} and source.source_uri.startswith(
            ("s3://", "local-object://")
        )

    def materialize(self, source: RawAssetRecord, *, refresh: bool) -> MaterializedSource:
        try:
            body = self._object_storage.get_bytes(
                source.source_uri,
                max_bytes=self.max_archive_bytes,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise ObjectStorageSourceConnectorError(str(exc)) from exc
        revision = hashlib.sha256(body).hexdigest()
        target = self.cache_dir / revision
        with self._materialization_lock(revision):
            complete_marker = target / ".nasus-complete"
            # Content-addressed targets are immutable. Refreshing the source
            # downloads and re-hashes the object, but never rewrites a complete
            # target that another worker may currently be reading.
            if not complete_marker.is_file():
                temp_target = Path(
                    tempfile.mkdtemp(prefix=f".{revision}.", dir=str(self.cache_dir))
                )
                try:
                    self._extract_bundle(body, temp_target)
                    complete_marker_temp = temp_target / ".nasus-complete"
                    complete_marker_temp.write_text(revision, encoding="utf-8")
                    if target.exists():
                        shutil.rmtree(target, ignore_errors=True)
                    temp_target.replace(target)
                except Exception:
                    shutil.rmtree(temp_target, ignore_errors=True)
                    raise
        return MaterializedSource(
            local_path=target,
            connector_kind=self.connector_kind,
            source_ref=source.source_uri,
            revision=revision,
            evidence_refs=(
                "connector:object-storage-bundle",
                f"object:{source.source_uri}",
                f"object-revision:sha256:{revision}",
            ),
        )

    def _extract_bundle(self, body: bytes, target: Path) -> None:
        archive_path = target / ".bundle.zip"
        archive_path.write_bytes(body)
        try:
            with ZipFile(archive_path) as archive:
                members = [item for item in archive.infolist() if not item.is_dir()]
                if not members:
                    raise ObjectStorageSourceConnectorError("source upload bundle contains no files")
                if len(members) > self.max_files:
                    raise ObjectStorageSourceConnectorError(
                        f"source upload bundle exceeds max file count {self.max_files}"
                    )
                total_size = sum(item.file_size for item in members)
                if total_size > self.max_extracted_bytes:
                    raise ObjectStorageSourceConnectorError(
                        f"source upload bundle exceeds max extracted bytes {self.max_extracted_bytes}"
                    )
                for member in members:
                    relative = PurePosixPath(member.filename)
                    if (
                        relative.is_absolute()
                        or ".." in relative.parts
                        or not relative.parts
                        or member.file_size < 0
                    ):
                        raise ObjectStorageSourceConnectorError(
                            f"source upload bundle contains unsafe path: {member.filename}"
                        )
                    destination = target.joinpath(*relative.parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source_handle, destination.open("wb") as output:
                        shutil.copyfileobj(source_handle, output, length=1024 * 1024)
        except BadZipFile as exc:
            raise ObjectStorageSourceConnectorError("source upload object is not a valid ZIP bundle") from exc
        finally:
            archive_path.unlink(missing_ok=True)

    @contextmanager
    def _materialization_lock(self, revision: str) -> Iterator[None]:
        lock_path = self.cache_dir / f".{revision}.lock"
        with lock_path.open("a+", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        try:
            return int(os.getenv(name, str(default)))
        except ValueError:
            return default


__all__ = ["ObjectStorageSourceConnector", "ObjectStorageSourceConnectorError"]
