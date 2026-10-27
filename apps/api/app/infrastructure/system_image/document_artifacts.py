from __future__ import annotations

import hashlib
import json

from ...domain.system_image.source_snapshots import snapshot_digest


class DocumentArtifacts:
    MAX_BYTES = 4 * 1024 * 1024

    def __init__(self, storage):
        self.storage = storage

    @staticmethod
    def key(project_id, digest):
        if len(digest) != 71 or not digest.startswith("sha256:") or any(c not in "0123456789abcdef" for c in digest[7:]):
            raise ValueError("invalid document artifact hash")
        return f"system-image/source-documents/{hashlib.sha256(project_id.encode()).hexdigest()}/{digest[7:]}.json"

    def put(self, project_id, payload):
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        if len(body) > self.MAX_BYTES or payload.get("project_id") != project_id:
            raise ValueError("invalid document artifact scope or size")
        digest = snapshot_digest(payload)
        stored = self.storage.put_bytes(self.key(project_id, digest), body, content_type="application/json")
        if stored.content_hash != digest:
            raise ValueError("document artifact write hash mismatch")
        self.read(project_id, stored.storage_ref, digest)
        return stored.storage_ref, digest

    def read(self, project_id, ref, digest):
        suffix = f"{self.storage.config.bucket}/{self.key(project_id, digest)}"
        if ref not in {f"s3://{suffix}", f"local-object://{suffix}"}:
            raise ValueError("document artifact namespace mismatch")
        try:
            body = self.storage.get_bytes(ref, max_bytes=self.MAX_BYTES)
        except Exception as exc:
            raise OSError("source document artifact is unavailable") from exc
        if "sha256:" + hashlib.sha256(body).hexdigest() != digest:
            raise ValueError("document artifact integrity mismatch")
        payload = json.loads(body)
        if (not isinstance(payload, dict) or payload.get("project_id") != project_id
                or snapshot_digest(payload) != digest):
            raise ValueError("document artifact scope mismatch")
        return payload
