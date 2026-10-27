"""The ToolInvocation is lifecycle authority; a job only pins dispatch and ownership."""
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from ...application.platform.account_models import UserProfile
from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import AuditEvent, EventPayload, ToolResult
from ...application.system_image.structure_builds import StructureBuildBinding, StructureBuildInput
from ...domain.system_image.build_plan import BuildPlanIntegrityError
from ...domain.system_image.source_access import SourceAccessDenied
from ...domain.system_image.source_snapshots import snapshot_digest
from ...domain.system_image.structure_work import StructureWorkBusy, StructureWorkLease, StructureWorkLost, StructureWorkCancelled
from .build_authorization_repository import BuildAuthorizationRepository
from .db_models import AuditEventRecord, ToolInvocationRecord, UserIdentityRecord
from .event_outbox_repository import EventOutboxRepository
from .source_snapshot_repository import SourceSnapshotRepository
from .structure_build_models import StructureBuildArtifactRecord
from .structure_build_repository import StructureBuildRepository
from .structure_job_models import StructureJobRecord as Job, StructureWorkLeaseRecord as Lease
from .structure_cancel_models import StructureCancellationRecord as Cancellation
from .unit_of_work import session_scope


class StructureJobRepository:
    LEASE_SECONDS = 45

    @staticmethod
    def _request(command):
        if command is None or command.tool_id != "system_image.build.structure":
            raise BuildPlanIntegrityError("Structural dispatch requires its canonical command.")
        return StructureBuildInput.model_validate({key: value for key, value in query_payload(command.input_payload).items()
            if key not in {"confirmed_by_user", "confirmed_at"}})

    @staticmethod
    def _hash(command):
        return snapshot_digest({"tool_id": command.tool_id, "input_payload": command.input_payload,
            "conversation_id": command.conversation_id, "initiator_surface": command.initiator_surface,
            "initiator_actor": command.initiator_actor, "target_scope": command.target_scope})

    @classmethod
    def cancellation_in_session(cls, session, command):
        row = session.get(Cancellation, command.id)
        if row is not None:
            from datetime import datetime
            from ...application.system_image.structure_cancel_inputs import STRUCTURE_CANCEL_TOOL, StructureCancelInput
            request = StructureCancelInput.model_validate(row.request_payload)
            stop = session.get(ToolInvocationRecord, row.cancellation_invocation_id)
            if (row.project_id != request.project_id or request.original_invocation_id != command.id
                    or row.command_hash != cls._hash(command)
                    or request.model_dump(exclude={"original_invocation_id"}) != cls._request(command).model_dump()
                    or stop is None or stop.id == command.id or stop.tool_id != STRUCTURE_CANCEL_TOOL
                    or stop.status not in {"running", "completed", "failed"}
                    or stop.input_payload.get("confirmed_by_user") is not True
                    or stop.input_payload.get("confirmed_actor_id") != row.actor_id
                    or StructureCancelInput.model_validate({key: value for key, value in query_payload(stop.input_payload).items()
                        if key not in {"confirmed_by_user", "confirmed_at"}}) != request):
                raise BuildPlanIntegrityError("Structural cancellation pins changed.")
            try:
                if datetime.fromisoformat(stop.input_payload["confirmed_at"]).tzinfo is None:
                    raise ValueError("missing timezone")
            except (KeyError, TypeError, ValueError) as error:
                raise BuildPlanIntegrityError("Structural cancellation has no confirmed authority.") from error
        return row

    @classmethod
    def require_not_cancelled_in_session(cls, session, command):
        if cls.cancellation_in_session(session, command) is not None:
            raise StructureWorkCancelled("Structural cancellation was durably requested.")

    @classmethod
    def _command(cls, session, invocation_id):
        command, job = session.get(ToolInvocationRecord, invocation_id), session.get(Job, invocation_id)
        request = cls._request(command)
        if (job is None or request.project_id != job.project_id or request.model_dump() != job.request_payload
                or cls._hash(command) != job.command_hash):
            raise BuildPlanIntegrityError("Structural dispatch pins changed or are missing.")
        if command.status == "completed" and session.get(StructureBuildArtifactRecord, invocation_id) is None:
            raise BuildPlanIntegrityError("Structural command has no committed candidate.")
        return command, job, request

    def register(self, request, invocation_id, actor_id):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
            if self._request(command) != request:
                raise BuildPlanIntegrityError("Structural dispatch request mismatch.")
            StructureBuildRepository.validate_in_session(session, StructureBuildBinding(**request.model_dump(), invocation_id=invocation_id))
            grant = BuildAuthorizationRepository.validate_grant_in_session(session, command)
            confirmer = grant.authorized_by if grant is not None else command.input_payload.get("confirmed_actor_id")
            if actor_id != confirmer:
                raise SourceAccessDenied("Structural dispatch actor differs from its confirmation.")
            job = session.get(Job, invocation_id)
            if job is None:
                session.add(Job(invocation_id=invocation_id, project_id=request.project_id, actor_id=actor_id,
                    command_hash=self._hash(command), request_payload=request.model_dump(),
                    created_at=session.scalar(select(func.clock_timestamp()))))
                session.flush()
                self._event(session, command, "system_image.build.structure.queued", {})
            else:
                self._command(session, invocation_id)
                if job.actor_id != actor_id:
                    raise SourceAccessDenied("Structural dispatch cannot inherit another actor's confirmation.")

    def command(self, invocation_id):
        with session_scope() as session:
            command, _, request = self._command(session, invocation_id)
            return request, command.status

    def execution(self, invocation_id):
        with session_scope() as session:
            _, job, _ = self._command(session, invocation_id)
            actor = session.get(UserIdentityRecord, job.actor_id)
            if actor is None or actor.status != "active":
                raise SourceAccessDenied("Structural confirming account is unavailable.")
            return UserProfile(id=actor.user_id, name=actor.display_name, email=actor.email, role=actor.role)

    def claim(self, invocation_id, owner_id):
        with session_scope() as session:
            command, job, _ = self._command(session, invocation_id)
            SourceSnapshotRepository._lock(session, job.project_id)
            command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
                .with_for_update().execution_options(populate_existing=True))
            if command.status != "running":
                raise StructureWorkLost("Structural command is no longer running.")
            row = session.scalar(select(Lease).where(Lease.invocation_id == invocation_id)
                .with_for_update().execution_options(populate_existing=True))
            now = session.scalar(select(func.clock_timestamp()))
            if row is not None and row.expires_at > now:
                raise StructureWorkBusy("Structural command has a live worker.")
            self.require_not_cancelled_in_session(session, command)
            lease = StructureWorkLease(job.project_id, invocation_id, owner_id, row.epoch + 1 if row else 1, job.command_hash)
            if row is None:
                row = Lease(invocation_id=invocation_id)
                session.add(row)
            row.owner_id, row.epoch = owner_id, lease.epoch
            row.renewed_at, row.expires_at = now, now + timedelta(seconds=self.LEASE_SECONDS)
            session.flush()
            self._event(session, command, "system_image.build.structure.worker_claimed", {"epoch": lease.epoch})
            return lease

    @classmethod
    def require_in_session(cls, session, command, lease, *, allow_cancel=False):
        current, job, _ = cls._command(session, lease.invocation_id)
        row = session.scalar(select(Lease).where(Lease.invocation_id == lease.invocation_id)
            .execution_options(populate_existing=True))
        if (current.id != command.id or command.status != "running" or job.project_id != lease.project_id
                or job.command_hash != lease.command_hash or row is None or row.owner_id != lease.owner_id
                or row.epoch != lease.epoch or row.expires_at <= session.scalar(select(func.clock_timestamp()))):
            raise StructureWorkLost("Structural activity no longer owns its command.")
        if not allow_cancel:
            cls.require_not_cancelled_in_session(session, current)
        return row

    def require_lease(self, lease, actor):
        with session_scope() as session:
            self.require_in_session(session, session.get(ToolInvocationRecord, lease.invocation_id), lease)
            job = session.get(Job, lease.invocation_id)
            user = session.get(UserIdentityRecord, job.actor_id)
            if user is None or user.status != "active" or user.user_id != actor.id or user.role != actor.role:
                raise SourceAccessDenied("Structural confirming account changed during execution.")

    def renew(self, lease):
        with session_scope() as session:
            session.scalar(select(Lease).where(Lease.invocation_id == lease.invocation_id).with_for_update())
            row = self.require_in_session(session, session.get(ToolInvocationRecord, lease.invocation_id), lease)
            now = session.scalar(select(func.clock_timestamp()))
            row.renewed_at, row.expires_at = now, now + timedelta(seconds=self.LEASE_SECONDS)

    def release(self, lease):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, lease.project_id)
            row = session.scalar(select(Lease).where(Lease.invocation_id == lease.invocation_id)
                .with_for_update().execution_options(populate_existing=True))
            if row is not None and (row.owner_id, row.epoch) == (lease.owner_id, lease.epoch):
                row.expires_at = session.scalar(select(func.clock_timestamp()))

    def finish(self, invocation_id, status, *, lease=None):
        if status not in {"completed", "cancelled", "failed"}:
            raise ValueError("Invalid structural termination.")
        with session_scope() as session:
            command, job, request = self._command(session, invocation_id)
            SourceSnapshotRepository._lock(session, job.project_id)
            command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
                .with_for_update().execution_options(populate_existing=True))
            if command.status != "running":
                return command.status
            work = session.scalar(select(Lease).where(Lease.invocation_id == invocation_id)
                .with_for_update().execution_options(populate_existing=True))
            if lease is not None:
                self.require_in_session(session, command, lease, allow_cancel=True)
            else:
                if work is not None and work.expires_at > session.scalar(select(func.clock_timestamp())):
                    raise StructureWorkBusy("Cannot terminate a live structural worker.")
            binding = StructureBuildBinding(**request.model_dump(), invocation_id=invocation_id)
            artifact = StructureBuildRepository.existing_in_session(session, binding)
            if artifact is not None:
                status = "completed"
            elif status == "completed":
                raise BuildPlanIntegrityError("Structural work cannot finish without its candidate.")
            cancellation = self.cancellation_in_session(session, command)
            if artifact is None and cancellation is not None:
                status = "cancelled"
            self.terminate_in_session(session, command, request, status, job.actor_id, work,
                caused_by=cancellation.cancellation_invocation_id if cancellation is not None else None)
            return status

    @classmethod
    def terminate_in_session(cls, session, command, request, status, actor_id, work, *, caused_by=None):
        artifact = StructureBuildRepository.existing_in_session(session,
            StructureBuildBinding(**request.model_dump(), invocation_id=command.id))
        if artifact is not None:
            status = "completed"
        elif status == "completed":
            raise BuildPlanIntegrityError("Structural work cannot finish without its candidate.")
        summary = {"completed": "Source-pinned structural candidate saved; semantic investigation and publication need separate review.",
            "cancelled": "Structural indexing cancelled; committed facts are retained.",
            "failed": "Structural work ended without a candidate. Inspect the fixed plan, access and original budget before new consent."}[status]
        refs = [f"build_plan:{request.plan_id}", f"image_revision:{artifact.image_revision_id}"] if artifact else []
        command.status, command.summary, command.revision = status, summary, command.revision + 1
        command.result_payload = ToolResult(invocation_id=command.id, status=status, summary=summary,
            object_refs=refs, requires_followup=True,
            followup_reason="structural_candidate_review" if artifact else "build_execution_authorization_review",
            next_recommended_tools=["query.system_image.revisions.read"] if artifact else []).model_dump()
        now = session.scalar(select(func.clock_timestamp()))
        audit = AuditEvent(id="audit_" + uuid4().hex[:10], occurred_at=now.isoformat(),
            tool_invocation_id=command.id, action=f"tool.invocation.{status}",
            entity_type="tool_invocation", entity_id=command.id,
            status=status, summary=summary, actor="system", actor_kind="system",
            conversation_id=command.conversation_id, agent_goal_id=command.input_payload.get("agent_goal_id"),
            object_refs=refs, evidence_refs=[], metadata={"project_id": request.project_id, "actor_id": actor_id,
                **({"caused_by": caused_by} if caused_by else {})})
        session.add(AuditEventRecord(**audit.model_dump(exclude={"metadata"}), event_metadata=audit.metadata))
        cls._event(session, command, "tool.invocation.updated", {"status": status, "summary": summary,
            "tool_id": command.tool_id})
        if work is not None:
            work.expires_at = now

    def pending(self, *, after_id="", limit=100):
        with session_scope() as session:
            return list(session.execute(select(Job.invocation_id, Job.project_id).join(ToolInvocationRecord,
                ToolInvocationRecord.id == Job.invocation_id).where(ToolInvocationRecord.status == "running",
                    Job.invocation_id > after_id).order_by(Job.invocation_id).limit(min(max(limit, 1), 100))).all())

    @staticmethod
    def _event(session, command, kind, patch):
        EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=kind,
            occurred_at=session.scalar(select(func.clock_timestamp())).isoformat(),
            correlation_id=command.conversation_id or command.id, entity_type="tool_invocation", entity_id=command.id,
            conversation_id=command.conversation_id, agent_goal_id=command.input_payload.get("agent_goal_id"),
            entity_version=command.revision, mutation_kind="replace" if kind == "tool.invocation.updated" else "append",
            patch=patch, query_keys=[["tool-invocation", command.id],
                ["system-image-build-plans", command.input_payload["project_id"]]]), session=session)
