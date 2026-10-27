import hashlib
import json

from ...domain.system_image.code_observation_archive import (
    MAX_OBSERVATION_BYTES, observation_summary, validate_observation_payload, verify_observation_report,
)
from ...domain.system_image.source_snapshots import snapshot_digest


class ArchivedCodeObservations:
    def __init__(self, storage):
        self.storage = storage

    @staticmethod
    def key(project_id, source_id, digest):
        namespace = hashlib.sha256(f"{project_id}\0{source_id}".encode()).hexdigest()
        return f"system-image/code-observations/{namespace}/{digest[7:]}.json"

    def put(self, payload):
        body = validate_observation_payload(payload)
        digest = snapshot_digest(payload)
        try:
            stored = self.storage.put_bytes(self.key(payload["project_id"], payload["source_id"], digest),
                body, content_type="application/json")
            if stored.content_hash != digest:
                raise ValueError("code observation storage digest mismatch")
            pin = {"artifact_ref": stored.storage_ref, "artifact_hash": digest, "summary": observation_summary(payload)}
            self.read({**payload, "provider": payload["result"]["provider"],
                "provider_version": payload["result"]["provider_version"], "observation_archive": pin})
            return pin
        except Exception as exc:
            raise ValueError("code observations could not be durably archived") from exc

    def read(self, report):
        pin = report["observation_archive"]
        scheme = "s3" if self.storage.config.s3_enabled else "local-object"
        expected = f"{scheme}://{self.storage.config.bucket}/" + self.key(
            report["project_id"], report["source_id"], pin["artifact_hash"])
        if pin["artifact_ref"] != expected:
            raise ValueError("code observation archive namespace mismatch")
        try:
            body = self.storage.get_bytes(expected, max_bytes=MAX_OBSERVATION_BYTES)
            if "sha256:" + hashlib.sha256(body).hexdigest() != pin["artifact_hash"]:
                raise ValueError("code observation archive digest mismatch")
            payload = json.loads(body)
            verify_observation_report(payload, report)
            return payload
        except Exception as exc:
            raise ValueError("code observation archive is unavailable or invalid") from exc
