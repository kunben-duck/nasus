from __future__ import annotations

from copy import deepcopy
import re
from uuid import uuid4

from sqlalchemy import select

from ...application.platform.project_models import VersionCreateRequest, VersionSummary
from ...application.platform.tool_models import EventPayload, ToolResult
from ...application.quality_loop.version_delivery_models import DeliveryCodeRevision, delivery_view
from ...domain.quality_loop.version_delivery import VersionDeliveryConflict, VersionDeliveryIntegrityError
from ...domain.system_image.source_snapshots import snapshot_digest
from .db_models import (AuditEventRecord, ConversationRecord, ProjectRecord, ProjectRoleBindingRecord,
    ReleaseReadinessRecord, ToolInvocationRecord, UserIdentityRecord, USWorkItemRecord, VersionRecord)
from .event_outbox_repository import EventOutboxRepository
from .image_publication_repository import ImagePublicationRepository
from .project_repository import ProjectRepository
from .source_snapshot_models import SourceBindingRecord, SourceRevisionRecord
from .unit_of_work import session_scope
from .version_delivery_models import ProjectDeliveryRecord, VersionCreationRecord, VersionImageBindingRecord


class VersionDeliveryRepository:
    def requirement_version(self, project_id, us_id):
        with session_scope() as session:
            us = session.get(USWorkItemRecord, us_id)
            if us is None or us.project_id != project_id:
                raise KeyError("Requirement not found in this project")
            return us.version_id

    def enabled(self, project_id):
        with session_scope() as session:
            return session.get(ProjectDeliveryRecord, project_id) is not None

    @staticmethod
    def _binding(session, project_id, version_id):
        row = session.get(VersionImageBindingRecord, version_id)
        if row is None:
            return None
        if (row.project_id != project_id or snapshot_digest(row.payload) != row.content_hash
                or row.payload.get("baseline") != row.payload.get("iteration_image")
                or any(row.payload["baseline"].get(key) != getattr(row, key) for key in
                       ("baseline_id", "publication_id", "image_revision_id"))):
            raise VersionDeliveryIntegrityError("Version image binding integrity failed")
        return deepcopy(row.payload)

    def read(self, project_id, version_id):
        with session_scope() as session:
            version = session.get(VersionRecord, version_id)
            if version is None or version.project_id != project_id:
                raise KeyError("Version not found")
            return ProjectRepository._to_version(version), self._binding(session, project_id, version_id)

    def code_revisions(self, project_id, members):
        values = []
        with session_scope() as session:
            for member in sorted(members, key=lambda value: value["binding_id"]):
                if member["source_type"] != "code" or member["status"] != "captured":
                    continue
                binding = session.get(SourceBindingRecord, member["binding_id"])
                revision = session.get(SourceRevisionRecord, member["source_revision_id"])
                if (binding is None or revision is None or binding.project_id != project_id
                        or revision.project_id != project_id or revision.binding_id != binding.binding_id
                        or binding.kind != "code"):
                    raise VersionDeliveryIntegrityError("Code revision is outside the published image")
                values.append(DeliveryCodeRevision(binding_id=binding.binding_id,
                    source_id=binding.legacy_source_id, source_revision_id=revision.source_revision_id,
                    repository=binding.external_identity, tracked_ref=binding.tracked_ref,
                    external_revision=revision.external_revision,
                    commit_sha=revision.external_revision if re.fullmatch(r"[0-9a-f]{40}", revision.external_revision) else None,
                    content_hash=revision.content_hash, manifest_hash=revision.manifest_hash).model_dump(mode="json"))
        return values

    @staticmethod
    def _actor(session, project_id, actor_id, expected_role):
        # Row locks fence membership/identity revocation through the commit.
        identity = session.scalar(select(UserIdentityRecord).where(UserIdentityRecord.user_id == actor_id)
            .with_for_update().execution_options(populate_existing=True))
        roles = session.scalars(select(ProjectRoleBindingRecord).where(
            ProjectRoleBindingRecord.project_id == project_id, ProjectRoleBindingRecord.user_id == actor_id,
            ProjectRoleBindingRecord.version_id.is_(None), ProjectRoleBindingRecord.session_id.is_(None),
            ProjectRoleBindingRecord.status == "active").with_for_update().execution_options(populate_existing=True)).all()
        if identity is not None and identity.status != "active":
            raise PermissionError("Version creation requires an active actor")
        if not (identity is not None and identity.role == "platform_admin") and (
                len(roles) != 1 or roles[0].role not in {"qa_lead", "project_admin", "platform_admin"}):
            raise PermissionError("Version creation requires current project QA lead access")
        if identity is not None:
            effective_role = "platform_admin" if identity.role == "platform_admin" else roles[0].role
            if effective_role != expected_role:
                raise PermissionError("Actor role changed before Version creation")

    @staticmethod
    def _canonical(session, project_id, request, invocation_id):
        invocation = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
            .with_for_update())
        if invocation is None or invocation.tool_id != "version.create" or invocation.status != "running":
            raise VersionDeliveryIntegrityError("Canonical running version.create invocation required")
        payload = invocation.input_payload
        conversation = session.get(ConversationRecord, invocation.conversation_id) if invocation.conversation_id else None
        resolved_project = payload.get("project_id") or (conversation.project_id if conversation else None)
        stored = VersionCreateRequest.model_validate({"name": "New Version", **{key: payload[key]
            for key in VersionCreateRequest.model_fields if key in payload}})
        stored = stored.model_copy(update={"name": stored.name.strip()})
        if resolved_project != project_id or stored != request or (
                conversation is not None and conversation.project_id not in {None, project_id}):
            raise VersionDeliveryIntegrityError("Version invocation scope or request mismatch")
        return invocation

    def create(self, project_id, request, *, invocation_id, actor_id, expected_role, recorded_at, prepare, verify, require_access):
        with session_scope() as session:
            # Same lock order as publication: source inventory, source ACL, command, actor.
            if session.get_bind().dialect.name == "postgresql":
                ImagePublicationRepository._lock(session, project_id)
            invocation = self._canonical(session, project_id, request, invocation_id)
            self._actor(session, project_id, actor_id, expected_role)
            project = session.scalar(select(ProjectRecord).where(ProjectRecord.id == project_id).with_for_update())
            if project is None:
                raise KeyError("Project not found")
            require_access()
            request_hash = snapshot_digest({"project_id": project_id, **request.model_dump(mode="json")})
            prior = session.get(VersionCreationRecord, invocation_id)
            if prior is not None:
                if (prior.project_id, prior.actor_id, prior.request_hash) != (project_id, actor_id, request_hash):
                    raise VersionDeliveryIntegrityError("Version invocation is already bound")
                version = session.get(VersionRecord, prior.version_id)
                if version is None or version.project_id != project_id:
                    raise VersionDeliveryIntegrityError("Created Version is missing")
                binding = self._binding(session, project_id, version.id)
                verify(binding)
                require_access()
                return ProjectRepository._to_version(version), binding
            opted_in = session.get(ProjectDeliveryRecord, project_id)
            if opted_in is not None and request.image_binding is None:
                raise VersionDeliveryConflict("image_binding is required for this delivery-enabled project")
            binding = prepare()
            if binding:
                pin = binding["baseline"]
                baseline, head = ImagePublicationRepository._target(session, project_id, pin["baseline_id"])
                if baseline["kind"] != "official" or baseline["source_version_id"] is not None:
                    raise VersionDeliveryConflict("A new Version requires an official project publication")
                if head is None or head["publication_id"] != request.image_binding.expected_head_id:
                    raise VersionDeliveryConflict("Publication head changed before Version creation")
            require_access()
            version = VersionSummary(id="ver_" + uuid4().hex, name=request.name, status="draft",
                branch_name="release/" + (re.sub(r"[^a-z0-9]+", "-", request.name.lower()).strip("-") or "version"),
                us_total=0, us_closed=0, pending_runs=0, pending_approvals=0)
            existing = session.scalars(select(VersionRecord).where(VersionRecord.project_id == project_id)).all()
            order = min((row.sort_order for row in existing), default=1) - 1
            session.add(VersionRecord(project_id=project_id, sort_order=order, **version.model_dump()))
            project.active_version = request.name
            session.add(ReleaseReadinessRecord(project_id=project_id, version_id=version.id, status="Draft",
                score=0, blockers=0, approvals_open=0, pending_merge=0, execution_health="No runs yet",
                summary="Version created; delivery work and release assessment have not been completed.", blocker_items=[]))
            session.flush()
            session.add(VersionCreationRecord(invocation_id=invocation_id, project_id=project_id, version_id=version.id,
                actor_id=actor_id, request_hash=request_hash, created_at=recorded_at))
            session.flush()
            if binding:
                session.add(VersionImageBindingRecord(project_id=project_id, version_id=version.id,
                    baseline_id=pin["baseline_id"], publication_id=pin["publication_id"],
                    image_revision_id=pin["image_revision_id"], payload=deepcopy(binding), content_hash=snapshot_digest(binding)))
                if opted_in is None:
                    session.add(ProjectDeliveryRecord(project_id=project_id, enabled_by_version_id=version.id, enabled_at=recorded_at))
            # A process can die after commit but before the handler emits its
            # response. Replaying the canonical key must still return completion.
            invocation.status = "completed"
            invocation.summary = "Created version " + version.name
            invocation.result_payload = ToolResult(invocation_id=invocation_id, status="completed",
                summary=invocation.summary, object_refs=["version:" + version.id],
                version_delivery=delivery_view(project_id, version, binding),
                next_recommended_tools=[] if binding else ["quality.scenario.generate"]).model_dump(mode="json")
            invocation.revision += 1
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=recorded_at, actor=actor_id,
                actor_kind=invocation.initiator_actor, action="version.created", entity_type="version", entity_id=version.id,
                status="completed", summary="Version created with immutable image pin." if binding else "Legacy Version created.",
                conversation_id=invocation.conversation_id, tool_invocation_id=invocation_id,
                agent_goal_id=invocation.input_payload.get("agent_goal_id"), object_refs=["version:" + version.id],
                evidence_refs=[], event_metadata={"project_id": project_id, "image_bound": binding is not None}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="version.created",
                occurred_at=recorded_at, correlation_id=project_id, tool_invocation_id=invocation_id,
                entity_type="version", entity_id=version.id, entity_version=1, mutation_kind="append",
                patch={"project_id": project_id, "version_id": version.id, "enabled": binding is not None},
                query_keys=[["project", project_id], ["version-delivery", project_id, version.id], ["versions", project_id]]), session=session)
            session.flush()
            require_access()
            return version, deepcopy(binding)
