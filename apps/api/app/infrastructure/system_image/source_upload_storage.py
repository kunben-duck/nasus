from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Sequence
from zipfile import ZIP_DEFLATED, ZipFile

from ...application.system_image.source_uploads import (
    SourceUploadApplicationService,
    SourceUploadFile,
    SourceUploadResult,
    UploadSourceType,
)
from ..storage import ObjectStorage


class ObjectStorageSourceUploadStorage:
    """Persist source uploads as immutable, portable object-storage bundles."""

    def __init__(self, object_storage: ObjectStorage) -> None:
        self._object_storage = object_storage

    def put_source_bundle(
        self,
        project_id: str,
        source_type: UploadSourceType,
        files: Sequence[SourceUploadFile],
    ) -> SourceUploadResult:
        body = io.BytesIO()
        with ZipFile(body, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
            for item in sorted(files, key=lambda value: value.filename):
                archive.writestr(item.filename, item.body)
        payload = body.getvalue()
        fingerprint = SourceUploadApplicationService.fingerprint(files)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        key = f"source-uploads/{project_id}/{source_type}/{timestamp}-{fingerprint[7:23]}.zip"
        stored = self._object_storage.put_bytes(
            key,
            payload,
            content_type="application/zip",
        )
        return SourceUploadResult(
            source_type=source_type,
            source_uri=stored.storage_ref,
            content_hash=fingerprint,
            file_count=len(files),
            byte_count=sum(len(item.body) for item in files),
            evidence_refs=[
                "connector:browser-upload",
                f"object:{stored.storage_ref}",
                f"bundle:{stored.content_hash}",
                *[f"file:{item.filename}" for item in files[:20]],
            ],
        )

__all__ = ["ObjectStorageSourceUploadStorage"]
