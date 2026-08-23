from __future__ import annotations

import hashlib
import os
import posixpath
from dataclasses import dataclass
from typing import Literal, Protocol, Sequence

from pydantic import BaseModel

from .ports import SystemImageWorkspacePort


UploadSourceType = Literal["us_doc", "test_asset"]


@dataclass(frozen=True)
class SourceUploadFile:
    filename: str
    content_type: str
    body: bytes


class SourceUploadResult(BaseModel):
    source_type: UploadSourceType
    source_uri: str
    content_hash: str
    file_count: int
    byte_count: int
    evidence_refs: list[str]


class SourceUploadStoragePort(Protocol):
    def put_source_bundle(
        self,
        project_id: str,
        source_type: UploadSourceType,
        files: Sequence[SourceUploadFile],
    ) -> SourceUploadResult: ...


class SourceUploadApplicationService:
    """Validate and persist browser-uploaded system-image source bundles."""

    def __init__(
        self,
        workspace: SystemImageWorkspacePort,
        storage: SourceUploadStoragePort,
        *,
        max_files: int | None = None,
        max_bytes: int | None = None,
        max_single_file_bytes: int | None = None,
    ) -> None:
        self._workspace = workspace
        self._storage = storage
        self.max_files = max_files or self._env_int("NASUS_SOURCE_UPLOAD_MAX_FILES", 100)
        self.max_bytes = max_bytes or self._env_int(
            "NASUS_SOURCE_UPLOAD_MAX_BYTES",
            50 * 1024 * 1024,
        )
        self.max_single_file_bytes = max_single_file_bytes or self._env_int(
            "NASUS_SOURCE_UPLOAD_MAX_SINGLE_FILE_BYTES",
            10 * 1024 * 1024,
        )

    def upload(
        self,
        project_id: str,
        source_type: str,
        files: Sequence[SourceUploadFile],
    ) -> SourceUploadResult:
        self.authorize_project(project_id)
        if source_type not in {"us_doc", "test_asset"}:
            raise ValueError("source_type must be us_doc or test_asset for file uploads")
        if not files:
            raise ValueError("at least one source file is required")
        if len(files) > self.max_files:
            raise ValueError(f"source upload exceeds max file count {self.max_files}")

        total_bytes = 0
        normalized: list[SourceUploadFile] = []
        seen_names: set[str] = set()
        for item in files:
            filename = self._safe_filename(item.filename)
            if filename in seen_names:
                raise ValueError(f"duplicate source filename: {filename}")
            seen_names.add(filename)
            size = len(item.body)
            if size == 0:
                raise ValueError(f"source file is empty: {filename}")
            if size > self.max_single_file_bytes:
                raise ValueError(
                    f"source file exceeds max single file bytes {self.max_single_file_bytes}: {filename}"
                )
            total_bytes += size
            if total_bytes > self.max_bytes:
                raise ValueError(f"source upload exceeds max total bytes {self.max_bytes}")
            normalized.append(
                SourceUploadFile(
                    filename=filename,
                    content_type=item.content_type or "application/octet-stream",
                    body=item.body,
                )
            )
        return self._storage.put_source_bundle(
            project_id,
            source_type,  # type: ignore[arg-type]
            normalized,
        )

    def authorize_project(self, project_id: str) -> None:
        """Fail before reading a multipart body when project access is invalid."""
        if not self._workspace.has_project(project_id):
            raise KeyError(project_id)
        self._workspace.require_project_access(project_id)

    @staticmethod
    def _safe_filename(filename: str) -> str:
        normalized = filename.strip().replace("\\", "/")
        normalized = posixpath.normpath(normalized).lstrip("/")
        if not normalized or normalized in {".", ".."} or normalized.startswith("../"):
            raise ValueError("source filename is invalid")
        if any(part in {"", ".", ".."} for part in normalized.split("/")):
            raise ValueError("source filename contains an unsafe path segment")
        return normalized

    @staticmethod
    def fingerprint(files: Sequence[SourceUploadFile]) -> str:
        digest = hashlib.sha256()
        for item in sorted(files, key=lambda value: value.filename):
            digest.update(item.filename.encode("utf-8"))
            digest.update(b"\0")
            digest.update(item.body)
        return f"sha256:{digest.hexdigest()}"

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        try:
            return int(os.getenv(name, str(default)))
        except ValueError:
            return default


__all__ = [
    "SourceUploadApplicationService",
    "SourceUploadFile",
    "SourceUploadResult",
    "SourceUploadStoragePort",
    "UploadSourceType",
]
