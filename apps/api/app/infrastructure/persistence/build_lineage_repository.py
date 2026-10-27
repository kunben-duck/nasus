from dataclasses import asdict

from sqlalchemy import select

from ...application.system_image.build_lineage import LINEAGE_SCHEMA, native_execution_payload, validate_lineage_payload
from ...domain.system_image.build_plan import BuildPlanIntegrityError
from ...domain.system_image.code_index_generation import CodeIndexLeaseLost
from ...domain.system_image.source_snapshots import snapshot_digest
from .build_lineage_models import StructureBuildLineageRecord
from .code_analysis_models import CodeAnalysisRecord
from .code_index_generation_models import CodeIndexGenerationRecord, CodeIndexProjectionRecord
from .code_index_generation_repository import CodeIndexGenerationRepository
from .db_models import ToolInvocationRecord
from .source_snapshot_models import SourceBindingRecord, SourceManifestMemberRecord
from .structure_build_models import StructureBuildArtifactRecord
from .unit_of_work import session_scope


class StructureBuildLineageRepository:
    @staticmethod
    def _native(session, native, *, project_id, binding_id, revision_id, invocation_id, projection_metadata):
        generations = session.scalars(select(CodeIndexGenerationRecord).where(
            CodeIndexGenerationRecord.invocation_id == invocation_id,
            CodeIndexGenerationRecord.binding_id == binding_id)).all()
        if native is None:
            observed = any(item["availability"] == "observed" and "prepare_index" in item["capabilities"]["operations"]
                for item in (projection_metadata or {}).get("providers", ()))
            if observed:
                raise BuildPlanIntegrityError("Actual native code generation was omitted from build lineage.")
            attempts = [asdict(CodeIndexGenerationRepository._pin(row)) for row in generations]
            if any((pin["project_id"], pin["binding_id"], pin["source_revision_id"], pin["invocation_id"]) != (
                    project_id, binding_id, revision_id, invocation_id) for pin in attempts):
                raise BuildPlanIntegrityError("Unused native generation differs from the build source.")
            return attempts
        if len(generations) != 1:
            raise BuildPlanIntegrityError("Actual native code generation is missing or ambiguous.")
        pin = CodeIndexGenerationRepository._pin(generations[0])
        if (native["generation"] != asdict(pin) or pin.project_id != project_id
                or pin.binding_id != binding_id or pin.source_revision_id != revision_id
                or pin.invocation_id != invocation_id):
            raise BuildPlanIntegrityError("Build lineage substituted a native generation.")
        protocol = CodeIndexGenerationRepository._protocol(session, pin, required=True)
        projection = session.get(CodeIndexProjectionRecord, pin.generation_id)
        if (projection is None or projection.project_id != project_id
                or projection.projection_hash != native["projection_hash"]
                or snapshot_digest(asdict(protocol)) != native["protocol_hash"]):
            raise BuildPlanIntegrityError("Build lineage native protocol or projection changed.")
        return []

    @classmethod
    def attach(cls, session, commit, candidate):
        binding = commit.binding
        artifact = session.get(StructureBuildArtifactRecord, binding.invocation_id)
        if (artifact is None or not artifact.lineage_required or artifact.project_id != binding.project_id
                or artifact.image_revision_id != candidate.image_revision_id):
            raise BuildPlanIntegrityError("Actual lineage requires its new structural commit marker.")
        selected = session.scalars(select(SourceManifestMemberRecord).where(
            SourceManifestMemberRecord.project_id == binding.project_id,
            SourceManifestMemberRecord.manifest_id == candidate.manifest_id,
            SourceManifestMemberRecord.source_type == "code",
            SourceManifestMemberRecord.status == "captured")).all()
        receipts = {item.source_id: item for item in commit.code_extractions}
        source_ids = {row.binding_id: session.get(SourceBindingRecord, row.binding_id).legacy_source_id for row in selected}
        if len(receipts) != len(commit.code_extractions) or set(receipts) != set(source_ids.values()):
            raise BuildPlanIntegrityError("Build lineage must capture every actual code extraction.")
        analyses = []
        for source in sorted(selected, key=lambda item: item.binding_id):
            extraction = receipts[source_ids[source.binding_id]]
            report = session.get(CodeAnalysisRecord, extraction.analysis_id)
            if (report is None or (report.project_id, report.binding_id, report.source_revision_id) != (
                    binding.project_id, source.binding_id, source.source_revision_id)
                    or snapshot_digest(report.payload) != report.report_hash
                    or report.payload.get("schema") != "nasus.code-analysis.v3"
                    or report.payload.get("source_id") != extraction.source_id):
                raise BuildPlanIntegrityError("Actual code analysis does not match its captured source.")
            native = native_execution_payload(extraction.native)
            unused = cls._native(session, native, project_id=binding.project_id, binding_id=source.binding_id,
                revision_id=source.source_revision_id, invocation_id=binding.invocation_id,
                projection_metadata=report.payload.get("projection"))
            analyses.append({"binding_id": source.binding_id, "source_revision_id": source.source_revision_id,
                "analysis_id": report.analysis_id, "report_hash": report.report_hash,
                "observation_archive_hash": report.payload["observation_archive"]["artifact_hash"],
                "merged_projection_hash": extraction.merged_projection_hash, "native": native,
                "unused_native_generations": unused})
        payload = {"schema": LINEAGE_SCHEMA, **asdict(binding), "image_revision_id": candidate.image_revision_id,
            "image_artifact_hash": candidate.artifact_hash, "manifest_id": candidate.manifest_id,
            "manifest_hash": candidate.manifest_hash, "analyses": analyses}
        validate_lineage_payload(payload)
        digest = snapshot_digest(payload)
        existing = session.get(StructureBuildLineageRecord, binding.invocation_id)
        if existing is None:
            session.add(StructureBuildLineageRecord(invocation_id=binding.invocation_id, project_id=binding.project_id,
                image_revision_id=candidate.image_revision_id, lineage_hash=digest, payload=payload))
        elif existing.lineage_hash != digest or existing.payload != payload:
            raise BuildPlanIntegrityError("Committed code build lineage cannot be replaced.")
        session.flush()

    def read(self, project_id, plan_id, image_revision_id):
        with session_scope() as session:
            artifacts = session.scalars(select(StructureBuildArtifactRecord).where(
                StructureBuildArtifactRecord.project_id == project_id, StructureBuildArtifactRecord.plan_id == plan_id,
                StructureBuildArtifactRecord.image_revision_id == image_revision_id).order_by(StructureBuildArtifactRecord.invocation_id)).all()
            if len(artifacts) > 64:
                raise BuildPlanIntegrityError("Build lineage exceeds the complete receipt bound.")
            records = []
            for artifact in artifacts:
                row = session.get(StructureBuildLineageRecord, artifact.invocation_id)
                if row is None:
                    if artifact.lineage_required:
                        raise BuildPlanIntegrityError("Required committed build lineage is missing.")
                    # Legacy commits have no execution attestation. Never synthesize one.
                    continue
                payload = row.payload
                validate_lineage_payload(payload)
                command = session.get(ToolInvocationRecord, artifact.invocation_id)
                if (not artifact.lineage_required or row.project_id != project_id or row.image_revision_id != image_revision_id
                        or snapshot_digest(payload) != row.lineage_hash
                        or command is None or command.tool_id != "system_image.build.structure"
                        or command.status not in {"running", "completed"}
                        or any(payload.get(key) != getattr(artifact, key) for key in (
                            "project_id", "plan_id", "plan_digest", "image_revision_id", "invocation_id", "executor_version", "target_baseline_id"))):
                    raise BuildPlanIntegrityError("Committed structural build lineage is corrupt.")
                for item in payload["analyses"]:
                    analysis = session.get(CodeAnalysisRecord, item["analysis_id"])
                    if (analysis is None or (analysis.project_id, analysis.binding_id, analysis.source_revision_id,
                            analysis.report_hash) != (project_id, item["binding_id"], item["source_revision_id"], item["report_hash"])
                            or snapshot_digest(analysis.payload) != analysis.report_hash):
                        raise BuildPlanIntegrityError("Committed build analysis pin is corrupt.")
                    try:
                        unused = self._native(session, item["native"], project_id=project_id, binding_id=item["binding_id"],
                            revision_id=item["source_revision_id"], invocation_id=artifact.invocation_id,
                            projection_metadata=analysis.payload.get("projection"))
                    except (KeyError, TypeError, ValueError, CodeIndexLeaseLost) as exc:
                        raise BuildPlanIntegrityError("Committed native build lineage failed verification.") from exc
                    if unused != item["unused_native_generations"]:
                        raise BuildPlanIntegrityError("Committed unused native attempts changed.")
                records.append((payload, row.lineage_hash))
            return tuple(records)
