"""Exact raw request/result envelope in private MinIO, physically reverified."""
import base64
from dataclasses import asdict
import hashlib
import json

from ...application.quality_loop.runner_port import OwnedTargetHttpExecution
from ...domain.quality_loop.http_fixtures import HttpFixtureInvalid
from ..runner.adapters import HttpAutomationRunner
from ..runner.http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from ..runner.owned_target_environment import _object
from ..runner.request_wire import runner_request_hash


SCHEMA = "nasus.http-fixture-execution-archive.v1"
MAX_BYTES = 35 * 1024 * 1024


class HttpFixtureExecutionArtifacts:
    def __init__(self, storage):
        if not storage.config.s3_enabled:
            raise HttpFixtureInvalid("backend fixture archives require private S3 storage")
        self.storage = storage
        self.verifier = OwnedHttpFixtureObservationVerifier()

    @staticmethod
    def _key(project_id, digest):
        from ...domain.system_image.image_revision import require_digest
        require_digest(digest)
        if type(project_id) is not str or not 1 <= len(project_id) <= 128:
            raise HttpFixtureInvalid("invalid fixture archive project")
        return "quality/http-fixture-journal/" + hashlib.sha256(project_id.encode()).hexdigest() + "/" + digest[7:] + ".json"

    def _reference(self, project_id, digest):
        return "s3://" + self.storage.config.bucket + "/" + self._key(project_id, digest)

    def put(self, parent, scope, phase, command, execution):
        self.verifier.verify(command, execution, environment_id=scope.environment_id, inventory_hash=scope.inventory_hash)
        if len(execution.request_body) > 512 * 1024:
            raise HttpFixtureInvalid("fixture original request exceeds its complete byte bound")
        payload = {"schema": SCHEMA, "project_id": scope.project_id, "parent": parent, "scope": asdict(scope),
            "phase": phase, "command": asdict(command), "request": base64.b64encode(execution.request_body).decode("ascii"),
            "result": base64.b64encode(execution.result_body).decode("ascii")}
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
        if len(body) > MAX_BYTES:
            raise HttpFixtureInvalid("complete fixture archive exceeds its bound; no bytes were truncated")
        digest = "sha256:" + hashlib.sha256(body).hexdigest()
        stored = self.storage.put_bytes(self._key(scope.project_id, digest), body, content_type="application/json")
        if stored.storage_ref != self._reference(scope.project_id, digest) or stored.content_hash != digest:
            raise HttpFixtureInvalid("fixture archive storage returned different original bytes")
        self.read(parent, scope, phase, command, stored.storage_ref, digest)
        return stored.storage_ref, digest

    def read(self, parent, scope, phase, command, ref, digest):
        if ref != self._reference(scope.project_id, digest):
            raise HttpFixtureInvalid("fixture archive is outside its private project namespace")
        try:
            body = self.storage.get_bytes(ref, max_bytes=MAX_BYTES)
            if len(body) > MAX_BYTES or "sha256:" + hashlib.sha256(body).hexdigest() != digest:
                raise HttpFixtureInvalid("fixture original archive bytes differ")
            value = _object(body)
            expected = {"schema": SCHEMA, "project_id": scope.project_id, "parent": parent,
                "scope": asdict(scope), "phase": phase, "command": json.loads(json.dumps(asdict(command)))}
            if set(value) != set(expected) | {"request", "result"} or any(value[key] != item for key, item in expected.items()):
                raise HttpFixtureInvalid("fixture original archive scope or command differs")
            request = base64.b64decode(value["request"], validate=True)
            result_body = base64.b64decode(value["result"], validate=True)
            if len(request) > 512 * 1024 or len(result_body) > 24 * 1024 * 1024:
                raise HttpFixtureInvalid("fixture original wire exceeds its complete byte bound")
            result = HttpAutomationRunner._result_from_payload(command, _object(result_body), request_hash=runner_request_hash(command))
            execution = OwnedTargetHttpExecution(result, request, result_body, scope.environment_id, scope.inventory_hash)
            self.verifier.verify(command, execution, environment_id=scope.environment_id, inventory_hash=scope.inventory_hash)
            return execution
        except Exception:
            raise HttpFixtureInvalid("fixture original archive is unavailable or cannot be verified") from None
