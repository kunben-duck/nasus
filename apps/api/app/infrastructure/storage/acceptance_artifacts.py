import hashlib
import json

from ...domain.quality_loop.acceptance_specification import AC_SCHEMA, AcceptanceIntegrityError, acceptance_digest
from ...domain.system_image.image_revision import ImageArtifactUnavailable, require_digest


class PinnedRequirementAuthorityArtifacts:
    MAX_BYTES = 49152
    schema = AC_SCHEMA
    schemas = None
    namespace = "acceptance-specifications"

    def __init__(self, storage):
        self.storage = storage

    @classmethod
    def _key(cls, project_id, digest):
        require_digest(digest)
        return f"quality/{cls.namespace}/{hashlib.sha256(project_id.encode()).hexdigest()}/{digest[7:]}.json"

    def put(self, project_id, payload):
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        if len(body) > self.MAX_BYTES:
            raise ValueError("acceptance artifact exceeds 48 KiB")
        digest = acceptance_digest(payload)
        stored = self.storage.put_bytes(self._key(project_id, digest), body, content_type="application/json")
        if stored.content_hash != digest:
            raise AcceptanceIntegrityError("acceptance artifact write mismatch")
        self.read(project_id, stored.storage_ref, digest)
        return stored.storage_ref, digest

    def read(self, project_id, ref, digest):
        suffix = self.storage.config.bucket + "/" + self._key(project_id, digest)
        if ref not in {"s3://" + suffix, "local-object://" + suffix}:
            raise AcceptanceIntegrityError("acceptance artifact namespace mismatch")
        try:
            body = self.storage.get_bytes(ref, max_bytes=self.MAX_BYTES)
        except Exception:
            raise ImageArtifactUnavailable("acceptance artifact unavailable") from None
        if "sha256:" + hashlib.sha256(body).hexdigest() != digest:
            raise AcceptanceIntegrityError("acceptance artifact digest mismatch")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            raise AcceptanceIntegrityError("acceptance artifact is not JSON") from None
        if (not isinstance(payload, dict) or payload.get("schema") not in (self.schemas or (self.schema,)) or payload.get("project_id") != project_id
                or acceptance_digest(payload) != digest):
            raise AcceptanceIntegrityError("acceptance artifact scope mismatch")
        return payload


class AcceptanceSpecificationArtifacts(PinnedRequirementAuthorityArtifacts):
    pass
