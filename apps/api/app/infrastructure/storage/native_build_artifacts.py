"""Private native outputs, complete runtime inventory and exact-source receipts."""
from hashlib import sha256
import json
from uuid import UUID

from ...domain.quality_loop.native_build import (
    MAX_ARTIFACT_BYTES, MAX_BUILD_LOG_BYTES, NativeBuildOutput, build_receipt,
)
from ...domain.shared.native_build_source import byte_digest
from ...domain.system_image.source_snapshots import snapshot_digest
from ...domain.system_image.image_revision import require_digest
from ..runner.native_maven_build import runtime_jar_inventory


class NativeBuildArtifacts:
    def __init__(self, storage):
        self.storage = storage

    def _prefix(self, build_id, request):
        if type(build_id) is not str or str(UUID(build_id)) != build_id:
            raise ValueError("native build ID must be a canonical UUID")
        return "native-builds/" + sha256(request.source.pin.project_id.encode()).hexdigest() + "/" + build_id

    def _ref(self, key):
        scheme = "s3" if self.storage.config.s3_enabled else "local-object"
        return scheme + "://" + self.storage.config.bucket + "/" + key

    def put(self, build_id, request, output):
        receipt = build_receipt(request, output)
        if output.runtime_inventory != runtime_jar_inventory(output.artifact):
            raise ValueError("native runtime inventory differs from actual artifact bytes")
        prefix = self._prefix(build_id, request)
        with self.storage.write_session():
            refs = {}
            for name, body in (("artifact", output.artifact), ("log", output.log)):
                key = prefix + "/" + name + "/" + byte_digest(body)[7:]
                saved = self.storage.put_bytes(key, body, content_type="application/java-archive" if name == "artifact" else "text/plain")
                if saved.content_hash != byte_digest(body) or saved.storage_ref != self._ref(key):
                    raise ValueError("native build object storage differs")
                refs[name] = saved.storage_ref
            payload = {"build_id": build_id, "receipt": receipt, "refs": refs}
            digest = snapshot_digest(payload)
            key = prefix + "/receipts/" + digest[7:] + ".json"
            saved = self.storage.put_json(key, payload)
            if saved.content_hash != digest or saved.storage_ref != self._ref(key):
                raise ValueError("native build receipt storage differs")
        return {"build_id": build_id, "artifact_ref": saved.storage_ref, "artifact_hash": digest,
                "request_digest": request.digest}

    def read(self, build_id, request, *, artifact_ref, artifact_hash):
        require_digest(artifact_hash)
        prefix = self._prefix(build_id, request)
        expected = self._ref(prefix + "/receipts/" + artifact_hash.removeprefix("sha256:") + ".json")
        if artifact_ref != expected:
            raise ValueError("native build receipt scope differs")
        with self.storage.read_session():
            payload = json.loads(self.storage.get_bytes(artifact_ref, max_bytes=4 * 1024 * 1024))
            if snapshot_digest(payload) != artifact_hash or payload.get("build_id") != build_id:
                raise ValueError("native build receipt digest differs")
            receipt, refs = payload["receipt"], payload["refs"]
            if (receipt.get("request_digest") != request.digest or receipt.get("source") != request.source.metadata()
                    or receipt.get("adapter") != request.adapter or receipt["artifact"]["path"] != request.artifact_path):
                raise ValueError("native build receipt differs from fixed input")
            bodies = {}
            for name, limit in (("artifact", MAX_ARTIFACT_BYTES), ("log", MAX_BUILD_LOG_BYTES)):
                metadata = receipt[name]
                require_digest(metadata["content_hash"])
                ref = self._ref(prefix + "/" + name + "/" + metadata["content_hash"].removeprefix("sha256:"))
                if refs[name] != ref:
                    raise ValueError("native build object scope differs")
                body = self.storage.get_bytes(ref, max_bytes=limit)
                if byte_digest(body) != metadata["content_hash"] or len(body) != metadata["byte_count"]:
                    raise ValueError("native build object bytes differ")
                bodies[name] = body
            output = NativeBuildOutput(request.digest, bodies["artifact"], bodies["log"], receipt["toolchain"],
                                       runtime_jar_inventory(bodies["artifact"]))
            if receipt != build_receipt(request, output):
                raise ValueError("native build receipt differs from fixed source and actual output")
        return {"receipt": receipt, "artifact": output.artifact, "log": output.log}
