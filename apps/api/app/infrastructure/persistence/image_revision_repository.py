from __future__ import annotations

from dataclasses import asdict, fields, replace
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from uuid import uuid4

from sqlalchemy import exists, select, text

from ...application.platform.tool_models import EventPayload
from ...domain.system_image.image_revision import (
    IMAGE_POLICY, ImageArtifactUnavailable, ImageObjectMember, ImageRevisionConflict, ImageRevisionIntegrityError, ImageRevisionSummary, require_frozen_inputs, member_payload,
)
from ...domain.system_image.source_snapshots import snapshot_digest
from .code_entity_models import CodeEntityRevisionRecord
from .event_outbox_repository import EventOutboxRepository
from .image_revision_models import ImageObjectMemberRecord, ImageRevisionInvocationRecord, ImageRevisionRecord
from .source_snapshot_models import SourceManifestHeadRecord, SourceManifestMemberRecord, SourceManifestRecord
from .source_snapshot_repository import SourceSnapshotRepository
from .source_evidence_models import CodeEntityEvidenceRecord
from .document_projection_models import SourceDocumentRevisionRecord, SourceDocumentEvidenceRecord
from .unit_of_work import session_scope
from .image_read_snapshot import current_image_read_snapshot, image_read_snapshot_scope


class ImageRevisionRepository:
    def __init__(self):
        self._read_snapshot = ContextVar("image_repository_read_snapshot", default=None)

    @contextmanager
    def verified_read_session(self):
        """One compilation's immutable metadata snapshot; not an ACL cache."""
        with image_read_snapshot_scope() as session:
            token = self._read_snapshot.set((session, {}))
            try:
                yield
            finally:
                self._read_snapshot.reset(token)

    def reviewed_invocation(self, request, invocation_id, *, tool_id="system_image.revisions.freeze_links"):
        from .db_models import ToolInvocationRecord
        from ...domain.system_image.image_membership import FREEZE_LINKS_TOOL, REVIEWED_IMAGE_POLICY
        from ...domain.system_image.semantic_membership import FREEZE_SEMANTIC_TOOL, SEMANTIC_IMAGE_POLICY
        if tool_id not in {FREEZE_LINKS_TOOL, FREEZE_SEMANTIC_TOOL}:
            raise ValueError("unsupported freeze command")
        with session_scope() as session:
            invocation = session.get(ToolInvocationRecord, invocation_id)
            if (invocation is None or invocation.tool_id != tool_id or invocation.status != "running"
                    or invocation.input_payload.get("confirmed_by_user") is not True
                    or any(invocation.input_payload.get(key) != value for key, value in request.model_dump(mode="json").items())):
                raise ImageRevisionIntegrityError("freeze replay requires the exact canonical request")
            ids = session.scalars(select(ImageRevisionRecord.image_revision_id).join(ImageRevisionInvocationRecord,
                ImageRevisionInvocationRecord.image_revision_id == ImageRevisionRecord.image_revision_id).where(
                ImageRevisionRecord.project_id == request.project_id, ImageRevisionRecord.policy_version.in_([REVIEWED_IMAGE_POLICY, SEMANTIC_IMAGE_POLICY]),
                ImageRevisionInvocationRecord.project_id == request.project_id,
                ImageRevisionInvocationRecord.invocation_id == invocation_id)).all()
            if len(ids) > 1:
                raise ImageRevisionIntegrityError("freeze invocation has multiple candidate outputs")
            return ids[0] if ids else None

    def pin_evidence(self, project_id, members):
        with session_scope() as session:
            ids = [member.entity_revision_id for member in members if member.kind == "code_entity"]
            rows = session.execute(select(CodeEntityEvidenceRecord.entity_revision_id, CodeEntityEvidenceRecord.evidence_id).where(
                CodeEntityEvidenceRecord.project_id == project_id, CodeEntityEvidenceRecord.entity_revision_id.in_(ids))).all()
            evidence = {}
            for revision_id, evidence_id in rows:
                evidence.setdefault(revision_id, []).append(evidence_id)
            doc_ids = [member.document_revision_id for member in members if member.kind == "source_document"]
            if doc_ids:
                for revision_id, evidence_id in session.execute(select(
                        SourceDocumentEvidenceRecord.document_revision_id, SourceDocumentEvidenceRecord.evidence_id).where(
                        SourceDocumentEvidenceRecord.project_id == project_id,
                        SourceDocumentEvidenceRecord.document_revision_id.in_(doc_ids))):
                    evidence.setdefault(revision_id, []).append(evidence_id)
            return tuple(replace(member, evidence_ids=tuple(sorted(evidence.get(
                member.document_revision_id or member.entity_revision_id, [])))) for member in members)

    @staticmethod
    def _summary(row):
        return ImageRevisionSummary(**{field.name: getattr(row, field.name) for field in fields(ImageRevisionSummary)
                                       if field.name != "publication"})

    def record(self, manifest, baseline_id, *, artifact_ref, artifact_hash, members, relationship_count,
               invocation_id, recorded_at, build_commit=None, review_commit=None):
        require_frozen_inputs(manifest)
        if build_commit is not None and review_commit is not None:
            raise ValueError("a candidate cannot combine structural execution and review admission")
        members = tuple(sorted(members, key=lambda item: item.object_id))
        if not members or len({item.object_id for item in members}) != len(members):
            raise ValueError("Image object membership is empty or duplicated.")
        membership_hash = snapshot_digest([member_payload(item) for item in members])
        with session_scope() as session:
            # Same project lock as capture: a new manifest cannot replace the
            # accepted inputs between the head check and candidate commit.
            SourceSnapshotRepository._lock(session, manifest.project_id)
            if build_commit is not None:
                from .structure_build_repository import StructureBuildRepository
                binding = build_commit.binding
                if (binding.project_id != manifest.project_id or binding.target_baseline_id != baseline_id
                        or binding.invocation_id != invocation_id):
                    raise ImageRevisionIntegrityError("Structural work commit scope mismatch.")
                target, plan = StructureBuildRepository.validate_in_session(session, binding)
                from .structure_job_models import StructureJobRecord
                if session.get(StructureJobRecord, invocation_id) is not None:
                    from .structure_job_repository import StructureJobRepository
                    from .db_models import ToolInvocationRecord
                    if build_commit.work_lease is None:
                        raise ImageRevisionIntegrityError("Queued structural work requires its active worker fence.")
                    StructureJobRepository.require_in_session(session, session.get(ToolInvocationRecord, invocation_id), build_commit.work_lease)
                elif build_commit.work_lease is not None:
                    raise ImageRevisionIntegrityError("Structural worker has no durable dispatch intent.")
                if (target != build_commit.target or plan.proposal.intent.source_manifest_id != manifest.manifest_id
                        or plan.proposal.intent.source_manifest_hash != manifest.content_hash):
                    raise ImageRevisionIntegrityError("Structural work target or input changed.")
                build_commit.require_current()
            head = session.get(SourceManifestHeadRecord, manifest.project_id)
            row = session.get(SourceManifestRecord, manifest.manifest_id)
            assertion_members = ()
            semantic_members = ()
            policy_version = IMAGE_POLICY
            if review_commit is not None:
                from .image_membership_repository import ImageMembershipRepository
                from ...domain.system_image.image_membership import reviewed_membership_digest, REVIEWED_IMAGE_POLICY
                from .semantic_membership_repository import SemanticMembershipRepository
                from ...application.system_image.semantic_membership import SemanticFreezeCommit
                from ...domain.system_image.semantic_membership import semantic_membership_digest, SEMANTIC_IMAGE_POLICY
                if invocation_id != review_commit.invocation_id:
                    raise ImageRevisionIntegrityError("freeze invocation mismatch")
                if isinstance(review_commit, SemanticFreezeCommit):
                    assertion_members, semantic_members = SemanticMembershipRepository.validate(
                        session, review_commit, manifest, baseline_id, members, relationship_count)
                else:
                    assertion_members = ImageMembershipRepository.validate(session, review_commit, manifest, baseline_id, members, relationship_count)
                    semantic_members = SemanticMembershipRepository.read(session, manifest.project_id, review_commit.request.parent_revision_id)
                    if semantic_members != review_commit.inherited_semantics:
                        raise ImageRevisionIntegrityError("reference freeze changed semantic membership")
                if len(assertion_members) + len(semantic_members) > 1000:
                    raise ImageRevisionIntegrityError("combined assertion membership exceeds budget")
                policy_version = SEMANTIC_IMAGE_POLICY if semantic_members else REVIEWED_IMAGE_POLICY
                membership_hash = (semantic_membership_digest([member_payload(item) for item in members],
                    [asdict(item) for item in assertion_members], [asdict(item) for item in semantic_members]) if semantic_members else
                    reviewed_membership_digest([member_payload(item) for item in members], [asdict(item) for item in assertion_members]))
                if row is not None:
                    canonical = SourceSnapshotRepository._manifest(session, row)
                    if replace(canonical, captured_at="") != manifest:
                        raise ImageRevisionIntegrityError("reviewed image source manifest mismatch")
                    manifest = canonical
            if build_commit is None and review_commit is None and (head is None or head.manifest_id != manifest.manifest_id):
                raise ImageRevisionConflict("Source inputs changed while the image was being built.")
            if row is None or SourceSnapshotRepository._manifest(session, row) != manifest:
                raise ImageRevisionIntegrityError("Image source manifest mismatch.")
            allowed = {item.binding_id: item.source_revision_id for item in manifest.members}
            code_ids = [item.entity_revision_id for item in members if item.kind == "code_entity"]
            code_rows = {item.entity_revision_id: item for item in session.scalars(select(CodeEntityRevisionRecord).where(
                CodeEntityRevisionRecord.project_id == manifest.project_id, CodeEntityRevisionRecord.entity_revision_id.in_(code_ids),
            ))}
            evidence_rows = {(item.entity_revision_id, item.evidence_id): item for item in session.scalars(
                select(CodeEntityEvidenceRecord).where(CodeEntityEvidenceRecord.project_id == manifest.project_id,
                    CodeEntityEvidenceRecord.entity_revision_id.in_(code_ids)))}
            bindings = {}
            document_ids = [item.document_revision_id for item in members if item.kind == "source_document"]
            documents = {item.document_revision_id: item for item in session.scalars(select(SourceDocumentRevisionRecord).where(
                SourceDocumentRevisionRecord.project_id == manifest.project_id,
                SourceDocumentRevisionRecord.document_revision_id.in_(document_ids)))} if document_ids else {}
            document_evidence = {(item.document_revision_id, item.evidence_id) for item in session.scalars(select(
                SourceDocumentEvidenceRecord).where(SourceDocumentEvidenceRecord.project_id == manifest.project_id,
                SourceDocumentEvidenceRecord.document_revision_id.in_(document_ids)))} if document_ids else set()
            for item in members:
                if item.kind == "legacy_observation":
                    bindings[item.object_id] = None
                    continue
                if item.kind == "source_document":
                    document = documents.get(item.document_revision_id)
                    if (document is None or document.source_revision_id != item.source_revision_id
                            or allowed.get(document.binding_id) != item.source_revision_id or not item.evidence_ids
                            or (document.parent_document_revision_id and document.parent_document_revision_id not in documents)
                            or any((item.document_revision_id, evidence_id) not in document_evidence for evidence_id in item.evidence_ids)):
                        raise ImageRevisionIntegrityError("Image document member or evidence is outside the selected source revision.")
                    bindings[item.object_id] = document.binding_id
                    continue
                code = code_rows.get(item.entity_revision_id)
                if (code is None or code.entity_id != item.entity_id or code.source_revision_id != item.source_revision_id
                        or allowed.get(code.binding_id) != item.source_revision_id):
                    raise ImageRevisionIntegrityError("Image code member does not match its source and entity revision.")
                bindings[item.object_id] = code.binding_id
                for evidence_id in item.evidence_ids:
                    association = evidence_rows.get((item.entity_revision_id, evidence_id))
                    if (association is None or association.project_id != manifest.project_id
                            or association.binding_id != code.binding_id or association.source_revision_id != item.source_revision_id):
                        raise ImageRevisionIntegrityError("Image evidence is outside its code member.")
            existing = session.scalar(select(ImageRevisionRecord).where(
                ImageRevisionRecord.project_id == manifest.project_id, ImageRevisionRecord.baseline_id == baseline_id,
                ImageRevisionRecord.manifest_id == manifest.manifest_id, ImageRevisionRecord.artifact_hash == artifact_hash,
            ))
            if existing is not None:
                if existing.membership_hash != membership_hash or existing.relationship_count != relationship_count:
                    raise ImageRevisionIntegrityError("Image candidate digest collision.")
                from .object_provenance_projection_v1 import ObjectProvenanceProjectorV1
                ObjectProvenanceProjectorV1().image(session, existing, write=False)
                from .relation_provenance_projection_v1 import RelationProvenanceProjectorV1
                RelationProvenanceProjectorV1().image(session, existing, write=False, native_verified=True)
                self._invocation(session, existing, invocation_id)
                if build_commit is not None:
                    StructureBuildRepository.attach(session, build_commit, existing)
                if review_commit is not None:
                    review_commit.require_current()
                return self._summary(existing)
            candidate = ImageRevisionRecord(image_revision_id=str(uuid4()), project_id=manifest.project_id,
                baseline_id=baseline_id, manifest_id=manifest.manifest_id, manifest_hash=manifest.content_hash,
                artifact_ref=artifact_ref, artifact_hash=artifact_hash, membership_hash=membership_hash,
                policy_version=policy_version,
                parent_revision_id=review_commit.request.parent_revision_id if review_commit else None,
                parent_artifact_hash=review_commit.request.parent_artifact_hash if review_commit else None,
                assertion_count=len(assertion_members) + len(semantic_members), recorded_at=recorded_at, status="candidate", object_count=len(members),
                code_member_count=len(code_ids), relationship_count=relationship_count)
            session.add(candidate)
            session.flush()
            for item in members:
                session.add(ImageObjectMemberRecord(image_revision_id=candidate.image_revision_id,
                    project_id=manifest.project_id, manifest_id=manifest.manifest_id,
                    binding_id=bindings[item.object_id], **asdict(item)))
            self._invocation(session, candidate, invocation_id)
            if review_commit is not None:
                ImageMembershipRepository.attach(session, candidate, assertion_members)
                SemanticMembershipRepository.attach(session, candidate, semantic_members)
            EventOutboxRepository().append(EventPayload(
                event_id=str(uuid4()), event_type="system_image.candidate.frozen", occurred_at=recorded_at,
                correlation_id=manifest.project_id, entity_type="image_revision", entity_id=candidate.image_revision_id,
                entity_version=0, mutation_kind="append", patch={"project_id": manifest.project_id,
                    "image_revision_id": candidate.image_revision_id}, query_keys=[["system-image", manifest.project_id]],
            ), session=session)
            if build_commit is not None:
                StructureBuildRepository.attach(session, build_commit, candidate)
            if review_commit is not None:
                session.flush()
                review_commit.require_current()
            return self._summary(candidate)

    @staticmethod
    def _invocation(session, row, invocation_id):
        if invocation_id and session.get(ImageRevisionInvocationRecord, (row.project_id, row.image_revision_id, invocation_id)) is None:
            session.add(ImageRevisionInvocationRecord(project_id=row.project_id,
                image_revision_id=row.image_revision_id, invocation_id=invocation_id))

    def get(self, project_id, image_revision_id):
        snapshot = self._read_snapshot.get()
        active = current_image_read_snapshot()
        if snapshot is not None and active is not None and snapshot[0] is active[0]:
            session, verified = snapshot
            key = (project_id, image_revision_id)
            if key not in verified:
                result = self._get(session, project_id, image_revision_id)
                if len(verified) >= 2:
                    del verified[next(iter(verified))]
                verified[key] = result
            return deepcopy(verified[key])
        with session_scope() as session:
            return self._get(session, project_id, image_revision_id)

    def _get(self, session, project_id, image_revision_id):
        row = session.scalar(select(ImageRevisionRecord).where(ImageRevisionRecord.project_id == project_id,
            ImageRevisionRecord.image_revision_id == image_revision_id))
        if row is None:
            raise KeyError("image revision not found")
        columns = [getattr(ImageObjectMemberRecord, column.name) for column in ImageObjectMemberRecord.__table__.columns]
        persisted = session.execute(select(*columns).where(
            ImageObjectMemberRecord.project_id == project_id, ImageObjectMemberRecord.image_revision_id == image_revision_id
        ).order_by(ImageObjectMemberRecord.object_id)).all()
        members = [ImageObjectMember(item.object_id, item.object_hash, item.kind, item.entity_id,
            item.entity_revision_id, item.source_revision_id, tuple(item.evidence_ids), item.document_revision_id) for item in persisted]
        from .image_membership_repository import ImageMembershipRepository
        from ...domain.system_image.image_membership import reviewed_membership_digest, REVIEWED_IMAGE_POLICY
        from .semantic_membership_repository import SemanticMembershipRepository
        from ...domain.system_image.semantic_membership import semantic_membership_digest, SEMANTIC_IMAGE_POLICY, validate_semantic_members
        assertions = ImageMembershipRepository.read(session, project_id, image_revision_id)
        semantics = SemanticMembershipRepository.read(session, project_id, image_revision_id)
        digest = (reviewed_membership_digest([member_payload(item) for item in members], [asdict(item) for item in assertions])
                  if row.policy_version == REVIEWED_IMAGE_POLICY else snapshot_digest([member_payload(item) for item in members]))
        if row.policy_version == SEMANTIC_IMAGE_POLICY:
            validate_semantic_members(semantics, [member_payload(item) for item in members], project_id)
            digest = semantic_membership_digest([member_payload(item) for item in members],
                [asdict(item) for item in assertions], [asdict(item) for item in semantics])
        elif semantics:
            raise ImageRevisionIntegrityError("legacy candidate cannot contain semantic members")
        if digest != row.membership_hash or len(assertions) + len(semantics) != row.assertion_count:
            raise ImageRevisionIntegrityError("Persisted image membership digest mismatch.")
        from .image_provenance_reads import verify_image_provenance
        verify_image_provenance(session, row, members=persisted)
        bindings = frozenset(session.scalars(select(SourceManifestMemberRecord.binding_id).where(
            SourceManifestMemberRecord.project_id == project_id, SourceManifestMemberRecord.manifest_id == row.manifest_id)))
        return self._summary(row), row.artifact_ref, bindings

    def list(self, project_id, *, binding_ids, after_id, limit):
        if not 1 <= limit <= 101:
            raise ValueError("Invalid image revision page size.")
        model, member = ImageRevisionRecord, SourceManifestMemberRecord
        # Aggregate candidates are indivisible: do not leak their names/counts
        # when even one input binding is inaccessible.
        denied = exists(select(1).where(member.project_id == model.project_id,
            member.manifest_id == model.manifest_id, member.binding_id.not_in(binding_ids)))
        with session_scope() as session:
            rows = session.scalars(select(model).where(model.project_id == project_id, ~denied,
                model.image_revision_id > after_id).order_by(model.image_revision_id).limit(limit)).all()
            return [self._summary(row) for row in rows]
