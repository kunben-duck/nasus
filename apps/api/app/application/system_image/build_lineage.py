"""Receipts from actual extraction, not caller-selected analysis diagnostics."""
from dataclasses import asdict, dataclass
import json
from typing import Optional, Protocol

from ...domain.system_image.build_plan import BuildPlanIntegrityError
from ...domain.system_image.code_index_generation import CodeIndexGenerationPin
from ...domain.system_image.image_revision import ImageRevisionIntegrityError, require_digest
from ...domain.system_image.source_snapshots import snapshot_digest


LINEAGE_SCHEMA = "nasus.structure-build-lineage.v1"


@dataclass(frozen=True)
class NativeCodeExecutionPin:
    generation: CodeIndexGenerationPin
    projection_hash: str
    protocol_hash: str

    def __post_init__(self):
        if not isinstance(self.generation, CodeIndexGenerationPin):
            raise BuildPlanIntegrityError("Invalid native code execution generation.")
        require_digest(self.projection_hash)
        require_digest(self.protocol_hash)


@dataclass(frozen=True)
class CodeExtractionReceipt:
    source_id: str
    analysis_id: str
    merged_projection_hash: str
    native: Optional[NativeCodeExecutionPin] = None

    def __post_init__(self):
        for value in (self.source_id, self.analysis_id):
            if (type(value) is not str or not value.strip() or len(value) > 128
                    or any(ord(char) < 32 for char in value)):
                raise BuildPlanIntegrityError("Invalid actual code extraction receipt.")
        require_digest(self.merged_projection_hash)
        if self.native is not None and not isinstance(self.native, NativeCodeExecutionPin):
            raise BuildPlanIntegrityError("Invalid actual native extraction receipt.")


class StructureBuildLineagePort(Protocol):
    def read(self, project_id, plan_id, image_revision_id): ...


class StructureBuildLineageApplicationService:
    def __init__(self, plans, images, code_analysis, repository: StructureBuildLineagePort):
        self.plans, self.images, self.code_analysis, self.repository = plans, images, code_analysis, repository

    def read(self, project_id, plan_id, image_revision_id, image_hash):
        scope = self.plans.authorization.scope(project_id)
        plan = self.plans.read(project_id, plan_id)
        header, _ = self.images.frozen_snapshot(project_id, image_revision_id)
        if (header.artifact_hash != image_hash or header.manifest_id != plan.proposal.intent.source_manifest_id
                or header.manifest_hash != plan.proposal.intent.source_manifest_hash):
            raise BuildPlanIntegrityError("Build lineage image differs from the fixed plan.")
        records = self.repository.read(project_id, plan_id, image_revision_id)
        expected = {(item.binding_id, item.source_revision_id) for item in plan.proposal.intent.sources
                    if item.source_type == "code" and item.status == "captured"}
        verified = []
        for payload, digest in records:
            validate_lineage_payload(payload)
            if (payload.get("schema") != LINEAGE_SCHEMA or snapshot_digest(payload) != digest
                    or payload.get("project_id") != project_id or payload.get("plan_id") != plan_id
                    or payload.get("plan_digest") != plan.plan_digest or payload.get("image_revision_id") != image_revision_id
                    or payload.get("image_artifact_hash") != image_hash or payload.get("manifest_id") != header.manifest_id
                    or payload.get("manifest_hash") != header.manifest_hash
                    or type(payload.get("analyses")) is not list
                    or len(payload["analyses"]) != len(expected)
                    or {(item["binding_id"], item["source_revision_id"]) for item in payload["analyses"]} != expected):
                raise BuildPlanIntegrityError("Committed build lineage scope or digest differs.")
            for item in payload["analyses"]:
                proof = self.code_analysis.verify_projection(project_id, item["source_revision_id"], item["analysis_id"])
                if proof != {key: item[key] for key in proof}:
                    raise BuildPlanIntegrityError("Actual build analysis no longer matches its archived projection.")
            verified.append({"lineage_hash": digest, **payload})
        self.plans.authorization.require_current(scope)
        return tuple(verified)


def native_execution_payload(pin):
    return asdict(pin) if pin is not None else None


def validate_lineage_payload(payload):
    try:
        fields = {"schema", "project_id", "plan_id", "plan_digest", "target_baseline_id", "invocation_id",
                  "executor_version", "image_revision_id", "image_artifact_hash", "manifest_id", "manifest_hash", "analyses"}
        if type(payload) is not dict or set(payload) != fields or payload["schema"] != LINEAGE_SCHEMA:
            raise ValueError("Invalid lineage envelope.")
        for key in fields - {"schema", "analyses", "plan_digest", "image_artifact_hash", "manifest_hash"}:
            value = payload[key]
            if type(value) is not str or not value.strip() or len(value) > 128 or any(ord(c) < 32 for c in value):
                raise ValueError("Invalid lineage identity.")
        for key in ("plan_digest", "image_artifact_hash", "manifest_hash"):
            require_digest(payload[key])
        if type(payload["analyses"]) is not list or not 1 <= len(payload["analyses"]) <= 64:
            raise ValueError("Invalid complete code analysis receipt set.")
        seen = set()
        for item in payload["analyses"]:
            if type(item) is not dict or set(item) != {"binding_id", "source_revision_id", "analysis_id", "report_hash",
                    "observation_archive_hash", "merged_projection_hash", "native", "unused_native_generations"}:
                raise ValueError("Invalid analysis lineage fields.")
            CodeExtractionReceipt(item["binding_id"], item["analysis_id"], item["merged_projection_hash"])
            CodeExtractionReceipt(item["source_revision_id"], item["analysis_id"], item["report_hash"])
            require_digest(item["observation_archive_hash"])
            if item["binding_id"] in seen:
                raise ValueError("Duplicate actual code source.")
            seen.add(item["binding_id"])
            if type(item["unused_native_generations"]) is not list or len(item["unused_native_generations"]) > 1:
                raise ValueError("Invalid unused native generation set.")
            for pin in item["unused_native_generations"]:
                CodeIndexGenerationPin(**pin)
            native = item["native"]
            if native is not None:
                if type(native) is not dict or set(native) != {"generation", "projection_hash", "protocol_hash"} or item["unused_native_generations"]:
                    raise ValueError("Invalid native execution receipt.")
                NativeCodeExecutionPin(CodeIndexGenerationPin(**native["generation"]), native["projection_hash"], native["protocol_hash"])
        if len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()) > 256 * 1024:
            raise ValueError("Complete lineage exceeds its bound.")
    except (KeyError, TypeError, ValueError, AttributeError, ImageRevisionIntegrityError, BuildPlanIntegrityError) as exc:
        raise BuildPlanIntegrityError("Committed build lineage has an invalid schema.") from exc
