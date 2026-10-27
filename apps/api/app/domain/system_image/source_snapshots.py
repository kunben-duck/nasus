from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Optional


def snapshot_digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceSnapshotArtifact:
    external_revision: str
    content_hash: str
    manifest_hash: str
    manifest_ref: str
    file_count: int
    byte_count: int
    policy_version: str = "nasus.source-snapshot.v1"

    def __post_init__(self) -> None:
        if not self.external_revision or not self.manifest_ref:
            raise ValueError("source snapshot requires revision and durable manifest")
        for digest in (self.content_hash, self.manifest_hash):
            if not digest.startswith("sha256:") or len(digest) != 71:
                raise ValueError("source snapshot requires SHA-256 digests")
            try:
                bytes.fromhex(digest[7:])
            except ValueError as exc:
                raise ValueError("source snapshot requires SHA-256 digests") from exc
        if self.file_count < 1 or self.byte_count < 0:
            raise ValueError("empty source snapshots cannot prove successful ingestion")


@dataclass(frozen=True)
class SourceManifestMember:
    binding_id: str
    source_type: str
    source_revision_id: Optional[str]
    status: str


@dataclass(frozen=True)
class CapturedSourceManifest:
    manifest_id: str
    project_id: str
    content_hash: str
    captured_at: str
    members: tuple[SourceManifestMember, ...]
    # A captured input is not an approved system-image baseline.
    stage: str = "captured"
