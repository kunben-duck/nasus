"""Private MinIO archives for complete original case wire, never local fallback."""
import hashlib
import json

from ...application.quality_loop.run_plan_case_execution import CASE_ARCHIVE_SCHEMA, CASE_FIXTURE_ARCHIVE_SCHEMA, MAX_CASE_ARCHIVE_BYTES
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.run_plan_case_execution import RunPlanCaseExecutionInvalid, require_id, require_hash


class RunPlanCaseArtifacts:
    def __init__(self, storage):
        self.storage = storage

    @staticmethod
    def _key(project_id, digest):
        require_id(project_id)
        require_hash(digest)
        return "quality/run-plan-cases/" + hashlib.sha256(project_id.encode()).hexdigest() + "/" + digest[7:] + ".json"

    @staticmethod
    def _validate(project_id, value):
        if (type(value) is not dict or type(value.get("schema")) is not str
                or value["schema"] not in {CASE_ARCHIVE_SCHEMA, CASE_FIXTURE_ARCHIVE_SCHEMA}
                or type(value.get("observation")) is not dict or value["observation"].get("project_id") != project_id):
            raise RunPlanCaseExecutionInvalid("case native archive is outside the original project")

    def _configured(self):
        if not self.storage.config.s3_enabled:
            raise RunPlanCaseExecutionInvalid("case native archives require private S3/MinIO; no local fallback")

    def put(self, project_id, payload):
        self._configured()
        self._validate(project_id, payload)
        try:
            body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise RunPlanCaseExecutionInvalid("complete case archive cannot be serialized") from None
        if len(body) > MAX_CASE_ARCHIVE_BYTES:
            raise RunPlanCaseExecutionInvalid("complete case archive exceeds its byte limit; nothing was truncated")
        digest = acceptance_digest(payload)
        stored = self.storage.put_bytes(self._key(project_id, digest), body, content_type="application/json")
        expected = "s3://" + self.storage.config.bucket + "/" + self._key(project_id, digest)
        if stored.content_hash != digest or stored.storage_ref != expected:
            raise RunPlanCaseExecutionInvalid("case archive storage returned different bytes or a public/foreign reference")
        self.read(project_id, stored.storage_ref, digest)
        return stored.storage_ref, digest

    def read(self, project_id, ref, digest):
        self._configured()
        if ref != "s3://" + self.storage.config.bucket + "/" + self._key(project_id, digest):
            raise RunPlanCaseExecutionInvalid("case archive namespace differs from the original private project")
        try:
            body = self.storage.get_bytes(ref, max_bytes=MAX_CASE_ARCHIVE_BYTES)
            if (type(body) is not bytes or len(body) > MAX_CASE_ARCHIVE_BYTES
                    or "sha256:" + hashlib.sha256(body).hexdigest() != digest):
                raise RunPlanCaseExecutionInvalid("case archive original bytes differ")
            def distinct(items):
                value = {}
                for key, item in items:
                    if key in value:
                        raise RunPlanCaseExecutionInvalid("case archive contains ambiguous JSON keys")
                    value[key] = item
                return value
            def reject(_):
                raise RunPlanCaseExecutionInvalid("case archive contains non-JSON constants")
            value = json.loads(body.decode("utf-8", errors="strict"), object_pairs_hook=distinct, parse_constant=reject)
            self._validate(project_id, value)
            if acceptance_digest(value) != digest:
                raise RunPlanCaseExecutionInvalid("case archive canonical digest differs")
            return value
        except Exception:
            raise RunPlanCaseExecutionInvalid("original private case archive is unavailable or cannot be verified") from None
