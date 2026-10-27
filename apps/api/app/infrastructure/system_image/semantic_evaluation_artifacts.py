from __future__ import annotations

import hashlib
import json

from ...application.system_image.semantic_evaluations import SEMANTIC_REPORT_SCHEMA
from ...domain.system_image.image_revision import ImageRevisionIntegrityError, ImageArtifactUnavailable, require_digest
from ...domain.system_image.source_snapshots import snapshot_digest


class SemanticEvaluationArtifacts:
    MAX_BYTES = 1024 * 1024

    def __init__(self, storage):
        self.storage = storage

    @staticmethod
    def _key(project_id, digest):
        require_digest(digest)
        return f"system-image/semantic-evaluations/{hashlib.sha256(project_id.encode()).hexdigest()}/{digest[7:]}.json"

    def put(self, project_id, payload):
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        if len(body) > self.MAX_BYTES:
            raise ValueError("semantic artifact exceeds 1 MiB")
        digest = snapshot_digest(payload)
        stored = self.storage.put_bytes(self._key(project_id, digest), body, content_type="application/json")
        if stored.content_hash != digest:
            raise ImageRevisionIntegrityError("semantic artifact write mismatch")
        self.read(project_id, stored.storage_ref, digest)
        return stored.storage_ref, digest

    def read(self, project_id, ref, digest):
        suffix = self.storage.config.bucket + "/" + self._key(project_id, digest)
        if ref not in {"s3://" + suffix, "local-object://" + suffix}:
            raise ImageRevisionIntegrityError("semantic artifact namespace mismatch")
        try:
            body = self.storage.get_bytes(ref, max_bytes=self.MAX_BYTES)
        except Exception:
            raise ImageArtifactUnavailable("semantic artifact unavailable") from None
        if "sha256:" + hashlib.sha256(body).hexdigest() != digest:
            raise ImageRevisionIntegrityError("semantic artifact digest mismatch")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            raise ImageRevisionIntegrityError("semantic artifact is not JSON") from None
        if (not isinstance(payload, dict) or payload.get("schema") != SEMANTIC_REPORT_SCHEMA or payload.get("project_id") != project_id
                or snapshot_digest(payload) != digest):
            raise ImageRevisionIntegrityError("semantic artifact scope mismatch")
        if not {"request", "invocation_id", "preview", "model_output", "evaluation", "evaluation_digest"}.issubset(payload):
            raise ImageRevisionIntegrityError("semantic artifact fields are incomplete")
        return payload
