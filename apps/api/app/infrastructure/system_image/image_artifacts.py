from __future__ import annotations

import hashlib
import json

from ...domain.system_image.image_revision import IMAGE_POLICY, ImageRevisionIntegrityError, ImageArtifactUnavailable, require_digest
from ...domain.system_image.image_membership import REVIEWED_IMAGE_POLICY
from ...domain.system_image.semantic_membership import SEMANTIC_IMAGE_POLICY
from ...domain.system_image.source_snapshots import snapshot_digest
from ..storage.object_storage import ObjectStorage


class ArchivedImageArtifacts:
    MAX_BYTES = 16 * 1024 * 1024

    def __init__(self, storage: ObjectStorage):
        self.storage = storage

    @staticmethod
    def _key(project_id, digest):
        require_digest(digest)
        return f"system-image/image-revisions/{hashlib.sha256(project_id.encode()).hexdigest()}/{digest[7:]}.json"

    def put(self, project_id, payload):
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(body) > self.MAX_BYTES:
            raise ValueError("Image candidate exceeds artifact size limit.")
        digest = snapshot_digest(payload)
        try:
            stored = self.storage.put_bytes(self._key(project_id, digest), body, content_type="application/json")
            if stored.content_hash != digest:
                raise ImageRevisionIntegrityError("Image artifact write failed integrity verification.")
            self.read(project_id, stored.storage_ref, digest)
        except ImageRevisionIntegrityError:
            raise
        except Exception as exc:
            raise ImageArtifactUnavailable("Image artifact could not be archived.") from exc
        return stored.storage_ref, digest

    def read(self, project_id, artifact_ref, artifact_hash):
        suffix = f"{self.storage.config.bucket}/{self._key(project_id, artifact_hash)}"
        if artifact_ref not in {f"s3://{suffix}", f"local-object://{suffix}"}:
            raise ImageRevisionIntegrityError("Image artifact namespace mismatch.")
        try:
            body = self.storage.get_bytes(artifact_ref, max_bytes=self.MAX_BYTES)
        except Exception as exc:
            raise ImageArtifactUnavailable("Image artifact is unavailable.") from exc
        if "sha256:" + hashlib.sha256(body).hexdigest() != artifact_hash:
            raise ImageRevisionIntegrityError("Image artifact digest mismatch.")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError) as exc:
            raise ImageRevisionIntegrityError("Invalid image artifact.") from exc
        if (not isinstance(payload, dict) or payload.get("project_id") != project_id
                or payload.get("schema") not in {IMAGE_POLICY, REVIEWED_IMAGE_POLICY, SEMANTIC_IMAGE_POLICY} or snapshot_digest(payload) != artifact_hash):
            raise ImageRevisionIntegrityError("Image artifact scope or schema mismatch.")
        return payload
