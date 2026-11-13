"""Project an evaluated requirement without moving the project's source/publication heads."""
from datetime import datetime, timezone
from dataclasses import replace
import hashlib

from sqlalchemy import select

from ...application.system_image.document_projections import DocumentProjectionApplicationService
from ...application.system_image.source_ports import SourceTextUnit
from ...application.system_image.system_image_models import RawAssetRecord, KnowledgeObject, KnowledgeDocumentReference
from ...domain.system_image.image_revision import build_image_artifact, member_payload, ImageRevisionIntegrityError
from ...domain.system_image.source_access import SourceAccessRule
from ...domain.system_image.source_snapshots import SourceManifestMember
from ..system_image.archived_document_projection import ArchivedDocumentProjection
from ..system_image.document_artifacts import DocumentArtifacts
from ..system_image.explicit_document_extractor import ExplicitDocumentExtractor
from .document_projection_repository import DocumentProjectionRepository
from .image_revision_models import ImageRevisionRecord, ImageObjectMemberRecord
from .source_snapshot_repository import SourceSnapshotRepository
from .source_snapshot_models import SourceBindingRecord, SourceRevisionRecord, SourceManifestMemberRecord
from .source_access_repository import SourceAccessRepository
from .requirement_review_models import RequirementReviewEventRecord
from .db_models import ToolInvocationRecord


def validate_projection_commit(session, proof, manifest, baseline_id, members, invocation_id):
    command = session.get(ToolInvocationRecord, invocation_id)
    reservation = session.scalar(select(RequirementReviewEventRecord).where(
        RequirementReviewEventRecord.invocation_id == invocation_id, RequirementReviewEventRecord.kind == "reserved"))
    parent = session.get(ImageRevisionRecord, proof["parent_image_id"])
    if (command is None or command.tool_id != "quality.requirement.evaluate" or command.status != "running"
            or command.input_payload.get("confirmed_by_user") is not True or reservation is None or parent is None
            or reservation.project_id != manifest.project_id or parent.project_id != manifest.project_id
            or reservation.payload["input"]["image_revision_id"] != parent.image_revision_id
            or parent.baseline_id != baseline_id or parent.assertion_count):
        raise ImageRevisionIntegrityError("Requirement projection has no exact canonical parent")
    source = session.get(SourceRevisionRecord, proof["source_revision_id"])
    binding = session.get(SourceBindingRecord, source.binding_id) if source else None
    if not binding or binding.legacy_source_id != "reqsrc_" + invocation_id or source.external_revision != reservation.revision_id:
        raise ImageRevisionIntegrityError("Requirement projection source is not the reserved revision")
    previous = session.scalars(select(SourceManifestMemberRecord).where(SourceManifestMemberRecord.manifest_id == parent.manifest_id)).all()
    signature = lambda item: (item.binding_id, item.source_type, item.source_revision_id, item.status)
    if {signature(item) for item in manifest.members} != {signature(item) for item in previous} | {
            (source.binding_id, "us_doc", source.source_revision_id, "captured")}:
        raise ImageRevisionIntegrityError("Requirement projection changed a pinned source")
    original = session.scalars(select(ImageObjectMemberRecord).where(
        ImageObjectMemberRecord.image_revision_id == parent.image_revision_id)).all()
    actual = {member.object_id: member for member in members}
    for item in original:
        if (item.object_id not in actual or actual[item.object_id].object_hash != item.object_hash
                or set(actual[item.object_id].evidence_ids) != set(item.evidence_ids)):
            raise ImageRevisionIntegrityError("Requirement projection changed an inherited object")
    additions = [item for item in members if item.object_id not in {row.object_id for row in original}]
    if not additions or any(item.kind != "source_document" or item.source_revision_id != proof["source_revision_id"] for item in additions):
        raise ImageRevisionIntegrityError("Requirement projection may only add its own source documents")


class RequirementImageProjection:
    def __init__(self, images, archive, image_artifacts, image_repository):
        self.images, self.archive = images, archive
        self.artifacts, self.repository = image_artifacts, image_repository

    def create(self, revision, assessment, *, invocation_id, actor_id, session):
        header, base = self.images.frozen_snapshot(revision.project_id, revision.image_revision_id)
        if header.artifact_hash != revision.image_artifact_hash or header.assertion_count:
            raise ValueError("Requirement projection needs the exact structural baseline; reviewed semantic overlays require an explicit merge")
        line = lambda value: " ".join(value.splitlines()).strip()
        body = (f"# US-{revision.revision_id} {line(revision.title)}\nDescription: {line(revision.text)}\n"
                f"Requirement revision: {revision.revision_id}\nEvaluation: {invocation_id}\n"
                "Authority: Model proposal; NOT approved.\n## Acceptance criteria\n")
        for index, criterion in enumerate(assessment.criteria, 1):
            oracle = criterion.oracle
            body += f"AC-{index}: {line(criterion.title)}. Given {line(oracle.preconditions)}; when {line(oracle.action)}; observe {line(oracle.observation)}; expect {line(oracle.expected_result)}.\n"
        path, data = "requirement.md", body.encode()
        source_id = "reqsrc_" + invocation_id
        digest = "sha256:" + hashlib.sha256(path.encode() + b"\0" + data).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        artifact = self.archive.capture(project_id=revision.project_id, source_id=source_id,
            files=[(path, data)], content_hash=digest, external_revision=revision.revision_id, excluded_directories=[])
        source = RawAssetRecord(id=source_id, project_id=revision.project_id, version_id=revision.version_id,
            source_type="us_doc", source_uri="nasus-requirement:" + invocation_id,
            content_ref=artifact.manifest_ref, content_hash=digest, ingestion_status="indexed",
            registered_at=now, registered_from_invocation_id=invocation_id)
        snapshots = SourceSnapshotRepository()
        source_revision_id = snapshots.record_capture(source, artifact, captured_at=now, session=session)
        binding = session.scalar(select(SourceBindingRecord).where(SourceBindingRecord.project_id == revision.project_id,
            SourceBindingRecord.legacy_source_id == source_id))
        binding_id = binding.binding_id
        access = SourceAccessRepository()
        access.set_policy(revision.project_id, binding_id, SourceAccessRule("restricted"),
            expected_epoch=access.load_snapshot(revision.project_id).acl_epoch, changed_by=actor_id, invocation_id=invocation_id, session=session)
        units = [SourceTextUnit(path, body, len(data), "sha256:" + hashlib.sha256(data).hexdigest())]
        documents = DocumentProjectionApplicationService(ExplicitDocumentExtractor(), ArchivedDocumentProjection(
            self.archive, DocumentArtifacts(self.archive.storage), DocumentProjectionRepository(write_session=session))).extract(source, units, captured_at=now)
        types = {"requirement": "SourceRequirement", "acceptance_criterion": "SourceAcceptanceCriterion", "business_rule": "SourceBusinessRule"}
        additions = [KnowledgeObject(id="DOC-" + item.entity_id, name=item.title, type=types.get(item.kind, item.kind),
            branch=header.baseline_id, confidence="source_observation", freshness="pinned",
            document_reference=KnowledgeDocumentReference(document_revision_id=item.document_revision_id,
                source_revision_id=item.source_revision_id)).model_dump(mode="json") for item in documents]
        manifest = snapshots.freeze_members(session, revision.project_id,
            [SourceManifestMember(**item) for item in base["source_members"]] + [
                SourceManifestMember(binding_id, "us_doc", source_revision_id, "captured")],
            captured_at=now, advance_head=False)
        payload, members = build_image_artifact(manifest, header.baseline_id, base["objects"] + additions, base["relationships"])
        members = self.repository.pin_evidence(revision.project_id, members, session=session)
        inherited = {item["object_id"]: item for item in base["members"]}
        members = tuple(replace(item, evidence_ids=tuple(inherited[item.object_id]["evidence_ids"]))
            if item.object_id in inherited else item for item in members)
        payload["members"] = [member_payload(item) for item in members]
        ref, digest = self.artifacts.put(revision.project_id, payload)
        child = self.repository.record(manifest, header.baseline_id, artifact_ref=ref, artifact_hash=digest,
            members=members, relationship_count=len(base["relationships"]), invocation_id=invocation_id, recorded_at=now,
            requirement_projection={"parent_image_id": header.image_revision_id, "source_revision_id": source_revision_id}, session=session)
        criteria = [item for item in documents if item.kind == "acceptance_criterion"]
        # ExplicitDocumentExtractor preserves the source AC order.
        criteria.sort(key=lambda item: item.payload["fields"][0]["start_line"])
        if len(criteria) != len(assessment.criteria):
            raise ValueError("Projected acceptance criteria do not match the model proposal")
        return {"image_revision_id": child.image_revision_id, "image_artifact_hash": child.artifact_hash,
            "parent_image_revision_id": header.image_revision_id, "manifest_id": child.manifest_id,
            "manifest_hash": child.manifest_hash, "baseline_id": child.baseline_id,
            "source_revision_id": source_revision_id, "binding_id": binding_id,
            "criteria": [{"object_id": "DOC-" + item.entity_id, "oracle": criterion.oracle.model_dump(),
                "title": criterion.title} for item, criterion in zip(criteria, assessment.criteria)]}
