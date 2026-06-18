from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from .models import RawAssetRecord


SourceType = Literal["code", "us_doc", "test_asset"]


@dataclass(frozen=True)
class SourceSpec:
    source_type: SourceType
    source_uri: str
    label: str | None = None


@dataclass(frozen=True)
class IngestedSource:
    content_hash: str
    content_ref: str
    evidence_refs: list[str]
    file_count: int
    byte_count: int


class SourceIngestionService:
    def normalize_specs(self, raw_specs: Any) -> list[SourceSpec]:
        if not isinstance(raw_specs, list):
            return []

        specs: list[SourceSpec] = []
        for item in raw_specs:
            if not isinstance(item, dict):
                continue
            source_type = item.get("source_type") or item.get("type")
            source_uri = item.get("source_uri") or item.get("uri") or item.get("path")
            if source_type not in {"code", "us_doc", "test_asset"} or not isinstance(source_uri, str):
                continue
            label = item.get("label")
            specs.append(SourceSpec(source_type=source_type, source_uri=source_uri, label=label if isinstance(label, str) else None))
        return specs

    def ingest(self, source: RawAssetRecord) -> IngestedSource:
        path = self._local_path(source.source_uri)
        if path is not None:
            return self._ingest_local_path(source, path)
        return self._ingest_external_reference(source)

    def _ingest_local_path(self, source: RawAssetRecord, path: Path) -> IngestedSource:
        if not path.exists():
            raise FileNotFoundError(f"source path does not exist: {path}")

        files = [path] if path.is_file() else [
            item
            for item in sorted(path.rglob("*"))
            if item.is_file() and not self._is_ignored_path(item)
        ]
        digest = hashlib.sha256()
        evidence_refs: list[str] = []
        byte_count = 0

        for file_path in files:
            relative = file_path.name if path.is_file() else str(file_path.relative_to(path))
            data = file_path.read_bytes()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(data)
            byte_count += len(data)
            evidence_refs.append(f"file:{relative}")

        content_hash = digest.hexdigest()
        return IngestedSource(
            content_hash=f"sha256:{content_hash}",
            content_ref=f"nasus://raw/{source.project_id}/{source.source_type}/{content_hash[:16]}",
            evidence_refs=self._typed_evidence_refs(source.source_type, evidence_refs, len(files), byte_count),
            file_count=len(files),
            byte_count=byte_count,
        )

    def _ingest_external_reference(self, source: RawAssetRecord) -> IngestedSource:
        digest = hashlib.sha256(source.source_uri.encode("utf-8")).hexdigest()
        return IngestedSource(
            content_hash=f"ref-sha256:{digest}",
            content_ref=f"nasus://raw/{source.project_id}/{source.source_type}/{digest[:16]}",
            evidence_refs=self._typed_evidence_refs(source.source_type, [f"uri:{source.source_uri}"], 0, 0),
            file_count=0,
            byte_count=0,
        )

    @staticmethod
    def _typed_evidence_refs(source_type: SourceType, refs: list[str], file_count: int, byte_count: int) -> list[str]:
        if source_type == "code":
            base = ["source:code", "parser:file-fingerprint"]
        elif source_type == "us_doc":
            base = ["source:historical-us", "parser:document-fingerprint"]
        else:
            base = ["source:test-assets", "parser:test-fingerprint"]
        return [*base, f"files:{file_count}", f"bytes:{byte_count}", *refs[:20]]

    @staticmethod
    def _local_path(source_uri: str) -> Path | None:
        parsed = urlparse(source_uri)
        if parsed.scheme == "file":
            return Path(parsed.path).expanduser().resolve()
        if parsed.scheme:
            return None
        return Path(source_uri).expanduser().resolve()

    @staticmethod
    def _is_ignored_path(path: Path) -> bool:
        ignored_parts = {".git", "node_modules", "__pycache__", ".venv", "dist", "build"}
        return any(part in ignored_parts for part in path.parts)
