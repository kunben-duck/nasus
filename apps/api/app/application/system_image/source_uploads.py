from __future__ import annotations

import hashlib
import os
import posixpath
import re
from dataclasses import dataclass
from typing import Literal, Protocol, Sequence

from pydantic import BaseModel

from .ports import SystemImageWorkspacePort
from ...domain.system_image.directory_snapshot import code_file_path


UploadSourceType = Literal["us_doc", "test_asset", "code"]


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
        code_write_scope=None,
        max_files: int | None = None,
        max_bytes: int | None = None,
        max_single_file_bytes: int | None = None,
    ) -> None:
        self._workspace = workspace
        self._storage = storage
        self._code_write_scope = code_write_scope
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
        self.authorize_project(project_id, source_type)
        if source_type not in {"us_doc", "test_asset", "code"}:
            raise ValueError("Unknown upload source type")
        if not files:
            raise ValueError("at least one source file is required")
        if len(files) > self.max_files:
            raise ValueError(f"source upload exceeds max file count {self.max_files}")

        total_bytes = 0
        normalized: list[SourceUploadFile] = []
        seen_names: set[str] = set()
        for item in files:
            filename = code_file_path(item.filename) if source_type == "code" else self._safe_filename(item.filename)
            identity = filename.casefold() if source_type == "code" else filename
            if identity in seen_names:
                raise ValueError(f"duplicate source filename: {filename}")
            seen_names.add(identity)
            size = len(item.body)
            if size == 0 and source_type != "code":
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
        if source_type == "code":
            for name in seen_names:
                parts = name.split("/")
                if any("/".join(parts[:i]) in seen_names for i in range(1, len(parts))):
                    raise ValueError("Directory contains conflicting file and directory paths")
            if any(re.search(br"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----", item.body) for item in normalized):
                raise ValueError("Directory contains private key material")
        return self._storage.put_source_bundle(
            project_id,
            source_type,  # type: ignore[arg-type]
            normalized,
        )

    def authorize_project(self, project_id: str, source_type: str = "") -> None:
        """Fail before reading a multipart body when project access is invalid."""
        if not self._workspace.has_project(project_id):
            raise KeyError(project_id)
        self._workspace.require_project_access(project_id)
        if source_type == "code" and (not self._code_write_scope or self._code_write_scope(project_id).effective_project_role
                                     not in {"tester", "qa_lead", "project_admin", "platform_admin"}):
            raise PermissionError("Project write access required")

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
