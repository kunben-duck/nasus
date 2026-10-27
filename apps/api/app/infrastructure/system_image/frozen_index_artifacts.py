import hashlib
import json

from ...domain.system_image.image_revision import ImageArtifactUnavailable, ImageRevisionIntegrityError, require_digest
from ...domain.system_image.source_snapshots import snapshot_digest


class FrozenIndexArtifacts:
    MAX_BYTES = 16 * 1024 * 1024

    def __init__(self, storage):
        self.storage = storage

    @staticmethod
    def _key(project_id, digest):
        require_digest(digest)
        return f"system-image/retrieval/{hashlib.sha256(project_id.encode()).hexdigest()}/{digest[7:]}.json"

    def put(self, project_id, payload):
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        if len(body) > self.MAX_BYTES:
            raise ValueError("index artifact exceeds 16 MiB")
        digest = snapshot_digest(payload)
        stored = self.storage.put_bytes(self._key(project_id, digest), body, content_type="application/json")
        if stored.content_hash != digest:
            raise ImageRevisionIntegrityError("index artifact write mismatch")
        self.read(project_id, stored.storage_ref, digest)
        return stored.storage_ref, digest

    def read(self, project_id, ref, digest):
        suffix = self.storage.config.bucket + "/" + self._key(project_id, digest)
        if ref not in {"s3://" + suffix, "local-object://" + suffix}:
            raise ImageRevisionIntegrityError("index artifact namespace mismatch")
        try:
            body = self.storage.get_bytes(ref, max_bytes=self.MAX_BYTES)
        except Exception:
            raise ImageArtifactUnavailable("index artifact unavailable") from None
        if "sha256:" + hashlib.sha256(body).hexdigest() != digest:
            raise ImageRevisionIntegrityError("index artifact hash mismatch")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            raise ImageRevisionIntegrityError("index artifact is not JSON") from None
        if (not isinstance(payload, dict) or payload.get("project_id") != project_id or snapshot_digest(payload) != digest
                or payload.get("schema") not in {"nasus.frozen-index.v1", "nasus.frozen-retrieval.v1",
                    "nasus.context-retrieval-batch.v1", "nasus.context-retrieval.v1"}):
            raise ImageRevisionIntegrityError("index artifact scope mismatch")
        return payload
