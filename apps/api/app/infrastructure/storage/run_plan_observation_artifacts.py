"""Content-addressed, bounded observation bytes under a private project prefix."""
import hashlib
import json

from ...application.quality_loop.run_plan_observation_archives import OBSERVATION_ARCHIVE_SCHEMAS, MAX_OBSERVATION_ARCHIVE_BYTES
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.run_plan_observations import RunPlanObservationInvalid
from ...domain.system_image.image_revision import require_digest


class RunPlanObservationArtifacts:
    def __init__(self, storage):
        self.storage = storage

    def reference(self, project_id, digest):
        protocol = "s3://" if self.storage.config.s3_enabled else "local-object://"
        return protocol + self.storage.config.bucket + "/" + self._key(project_id, digest)

    @staticmethod
    def _key(project_id, digest):
        require_digest(digest)
        if type(project_id) is not str or not 1 <= len(project_id) <= 128:
            raise RunPlanObservationInvalid("observation archive project is invalid")
        return "quality/run-plan-observations/" + hashlib.sha256(project_id.encode()).hexdigest() + "/" + digest[7:] + ".json"

    def put(self, project_id, payload):
        if type(payload) is not dict or payload.get("schema") not in OBSERVATION_ARCHIVE_SCHEMAS or payload.get("project_id") != project_id:
            raise RunPlanObservationInvalid("observation archive scope is invalid")
        try:
            body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise RunPlanObservationInvalid("observation archive cannot be serialized") from None
        if len(body) > MAX_OBSERVATION_ARCHIVE_BYTES:
            raise RunPlanObservationInvalid("complete observation archive exceeds 32 MiB; nothing was truncated")
        digest = "sha256:" + hashlib.sha256(body).hexdigest()
        stored = self.storage.put_bytes(self._key(project_id, digest), body, content_type="application/json")
        if stored.content_hash != digest:
            raise RunPlanObservationInvalid("observation archive storage returned a different hash")
        self.read(project_id, stored.storage_ref, digest)
        return stored.storage_ref, digest

    def read(self, project_id, ref, digest):
        suffix = self.storage.config.bucket + "/" + self._key(project_id, digest)
        if ref not in {"s3://" + suffix, "local-object://" + suffix}:
            raise RunPlanObservationInvalid("observation archive namespace differs")
        try:
            body = self.storage.get_bytes(ref, max_bytes=MAX_OBSERVATION_ARCHIVE_BYTES)
            if len(body) > MAX_OBSERVATION_ARCHIVE_BYTES or "sha256:" + hashlib.sha256(body).hexdigest() != digest:
                raise RunPlanObservationInvalid("observation archive bytes differ")
            def distinct(items):
                value = {}
                for key, item in items:
                    if key in value:
                        raise RunPlanObservationInvalid("observation archive contains ambiguous JSON keys")
                    value[key] = item
                return value
            def reject_constant(_value):
                raise RunPlanObservationInvalid("observation archive contains non-JSON constants")
            value = json.loads(body.decode("utf-8", errors="strict"), object_pairs_hook=distinct, parse_constant=reject_constant)
            if (type(value) is not dict or value.get("schema") not in OBSERVATION_ARCHIVE_SCHEMAS
                    or value.get("project_id") != project_id or acceptance_digest(value) != digest):
                raise RunPlanObservationInvalid("observation archive content differs")
        except Exception:
            raise RunPlanObservationInvalid("observation archive is unavailable or cannot be verified") from None
        return value
