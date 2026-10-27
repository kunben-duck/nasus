import hashlib
import json

from ...domain.system_image.context_pack import CONTEXT_SCHEMA, ContextPackIntegrityError, canonical_bytes
from ...domain.system_image.image_revision import ImageArtifactUnavailable, require_digest
from ...domain.system_image.source_snapshots import snapshot_digest


class ContextPackArtifacts:
    MAX_BYTES = 1024 * 1024

    def __init__(self, storage):
        self.storage = storage

    @staticmethod
    def _key(project_id, digest):
        require_digest(digest)
        return f"system-image/context-packs/{hashlib.sha256(project_id.encode()).hexdigest()}/{digest[7:]}.json"

    def put(self, project_id, payload):
        body, digest = canonical_bytes(payload), snapshot_digest(payload)
        if len(body) > self.MAX_BYTES:
            raise ValueError("context derivation exceeds 1 MiB; split scope explicitly")
        stored = self.storage.put_bytes(self._key(project_id, digest), body, content_type="application/json")
        if stored.content_hash != digest:
            raise ContextPackIntegrityError("context write digest mismatch")
        self.read(project_id, stored.storage_ref, digest)
        return stored.storage_ref, digest

    def read(self, project_id, ref, digest):
        suffix = self.storage.config.bucket + "/" + self._key(project_id, digest)
        if ref not in {"s3://" + suffix, "local-object://" + suffix}:
            raise ContextPackIntegrityError("context artifact namespace mismatch")
        try:
            body = self.storage.get_bytes(ref, max_bytes=self.MAX_BYTES)
        except Exception:
            raise ImageArtifactUnavailable("context artifact unavailable") from None
        if "sha256:" + hashlib.sha256(body).hexdigest() != digest:
            raise ContextPackIntegrityError("context artifact digest mismatch")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            raise ContextPackIntegrityError("context artifact is not JSON") from None
        if not isinstance(payload, dict) or payload.get("schema") != CONTEXT_SCHEMA or payload.get("project_id") != project_id or snapshot_digest(payload) != digest:
            raise ContextPackIntegrityError("context artifact scope mismatch")
        return payload
