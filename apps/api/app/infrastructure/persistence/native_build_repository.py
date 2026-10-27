"""One native attempt per confirmed command; original output and Outbox are atomic."""
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import func, select

from ...application.platform.account_models import UserProfile
from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload, ToolResult
from ...application.quality_loop.native_build_inputs import (
    NATIVE_BUILD_TOOL, NATIVE_BUILD_CANCEL_TOOL, NativeBuildCommand, NativeBuildTarget, NativeBuildOutcomeUnknown,
)
from ...application.quality_loop.generation_work_lease import (
    GenerationWorkLease, GenerationLeaseBusy, GenerationLeaseLost, GENERATION_LEASE_SECONDS,
)
from ...domain.system_image.source_snapshots import snapshot_digest
from .db_models import AuditEventRecord, ToolInvocationRecord, UserIdentityRecord, ProjectRoleBindingRecord
from .image_revision_models import ImageRevisionRecord
from .source_snapshot_models import SourceRevisionRecord, SourceManifestMemberRecord
from .native_build_models import NativeBuildReservationRecord as Reservation, NativeBuildResultRecord as Result
from .native_build_models import NativeBuildWorkLeaseRecord as Lease, NativeBuildCancellationRecord as Cancellation
from .event_outbox_repository import EventOutboxRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .test_design_result_repository import TestDesignResultRepository
from .unit_of_work import session_scope


class NativeBuildRepository:
    @staticmethod
    def _request(command):
        if (command is None or command.tool_id != NATIVE_BUILD_TOOL
                or command.input_payload.get("confirmed_by_user") is not True):
            raise ValueError("native build requires a confirmed canonical command")
        return NativeBuildCommand.model_validate({key: value for key, value in query_payload(command.input_payload).items()
            if key not in {"confirmed_at", "confirmed_by_user"}})

    @staticmethod
    def _actor(session, project_id, actor_id, *, lock=True):
        if type(lock) is not bool:
            raise ValueError("native actor guard requires an explicit locking mode")
        actor_query = select(UserIdentityRecord).where(UserIdentityRecord.user_id == actor_id)
        role_query = select(ProjectRoleBindingRecord).where(ProjectRoleBindingRecord.project_id == project_id,
            ProjectRoleBindingRecord.user_id == actor_id, ProjectRoleBindingRecord.version_id.is_(None),
            ProjectRoleBindingRecord.session_id.is_(None), ProjectRoleBindingRecord.status == "active")
        # Row locking alone does not refresh identities already held by this Session.
        actor_query = actor_query.execution_options(populate_existing=True)
        role_query = role_query.execution_options(populate_existing=True)
        actor = session.scalar(actor_query.with_for_update() if lock else actor_query)
        roles = session.scalars(role_query.with_for_update() if lock else role_query).all()
        if (actor is None or actor.status != "active" or (actor.role != "platform_admin"
                and (len(roles) != 1 or roles[0].role != "project_admin"))):
            raise PermissionError("native build requires an active project administrator")
        return actor

    @classmethod
    def _canonical(cls, session, request, invocation_id, actor_id, *, historical=False):
        query = select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
        command = session.scalar(query if historical else query.with_for_update())
        if (cls._request(command) != request or command.input_payload.get("confirmed_actor_id") != actor_id
                or command.status not in ({"running", "completed", "failed", "cancelled"} if historical else {"running"})):
            raise ValueError("native build original request or confirming actor differs")
        TestDesignResultRepository._project_scope(session, command, request.project_id)
        if not historical:
            try:
                confirmed = datetime.fromisoformat(str(command.input_payload.get("confirmed_at", "")))
                fresh = confirmed.tzinfo is not None and 0 <= (datetime.now(timezone.utc) - confirmed).total_seconds() <= 900
            except (ValueError, OverflowError):
                fresh = False
            if not fresh:
                raise ValueError("native build confirmation is not fresh")
            cls._actor(session, request.project_id, actor_id)
        return command

    @staticmethod
    def _digest(command):
        return snapshot_digest({"tool_id": command.tool_id, "input_payload": command.input_payload})

    @classmethod
    def _lease(cls, session, command, lease):
        row = session.scalar(select(Lease).where(Lease.invocation_id == lease.invocation_id)
            .execution_options(populate_existing=True))
        now = session.scalar(select(func.clock_timestamp()))
        if (command is None or command.status != "running" or command.id != lease.invocation_id
                or command.input_payload.get("project_id") != lease.project_id or row is None
                or (row.project_id, row.owner_id, row.epoch, row.request_digest)
                    != (lease.project_id, lease.owner_id, lease.epoch, lease.request_digest)
                or row.expires_at <= now or cls._digest(command) != lease.request_digest):
            raise GenerationLeaseLost("native build worker no longer owns the command")
        return row

    @classmethod
    def _value(cls, row):
        if row is None:
            return None
        columns = {column.name for column in row.__table__.columns} - {"payload", "content_hash"}
        if (type(row.payload) is not dict or snapshot_digest(row.payload) != row.content_hash
                or any(row.payload.get(key) != getattr(row, key) for key in columns)):
            raise ValueError("native build registration digest differs")
        return row.payload

    @classmethod
    def _source(cls, session, request, source):
        pin = source["pin"]
        image = session.get(ImageRevisionRecord, request.image_revision_id)
        revision = session.get(SourceRevisionRecord, request.source_revision_id)
        member = session.get(SourceManifestMemberRecord, (pin["manifest_id"], request.binding_id))
        if (image is None or revision is None or member is None or image.project_id != request.project_id
                or image.artifact_hash != request.image_artifact_hash or image.manifest_id != pin["manifest_id"]
                or image.manifest_hash != pin["manifest_hash"] or member.project_id != request.project_id
                or member.source_type != "code" or member.status != "captured" or member.source_revision_id != request.source_revision_id
                or revision.project_id != request.project_id or revision.binding_id != request.binding_id
                or revision.content_hash != pin["content_hash"] or revision.external_revision != pin["external_revision"]
                or revision.manifest_hash != pin["snapshot_manifest_hash"]
                or any(pin[key] != getattr(request, key) for key in
                    ("project_id", "image_revision_id", "image_artifact_hash", "binding_id", "source_revision_id"))):
            raise ValueError("native build source is not the original registered image member")

    @classmethod
    def _inspection(cls, session, project_id, invocation_id):
        command = session.get(ToolInvocationRecord, invocation_id)
        request = cls._request(command)
        if request.project_id != project_id:
            raise PermissionError("native build belongs to another project")
        reservation = cls._value(session.get(Reservation, invocation_id))
        result = cls._value(session.get(Result, invocation_id))
        if reservation is not None:
            cls._canonical(session, request, invocation_id, reservation["actor_id"], historical=True)
            if (reservation["request"] != request.model_dump(mode="json")
                    or reservation["request_hash"] != snapshot_digest(request.model_dump(mode="json"))
                    or snapshot_digest(reservation["operator_policy"]) != request.operator_policy_digest):
                raise ValueError("native build reservation input differs")
            cls._source(session, request, {"pin": reservation["source_pin"]})
        if result is not None and (reservation is None or result["build_id"] != reservation["build_id"]
                or result["project_id"] != project_id or result["request_digest"] != request.request_digest):
            raise ValueError("native build result ancestry differs")
        work = session.get(Lease, invocation_id)
        worker = ("none" if work is None else "active" if command.status == "running"
            and work.expires_at > session.scalar(select(func.clock_timestamp())) else "expired")
        return {"request": request.model_dump(mode="json"), "status": command.status, "worker": worker,
                "reservation": reservation, "result": result}

    def inspect(self, project_id, invocation_id):
        with session_scope() as session:
            return self._inspection(session, project_id, invocation_id)

    def require_running(self, request, invocation_id, actor_id):
        with session_scope() as session:
            self._canonical(session, request, invocation_id, actor_id)

    def command(self, invocation_id):
        with session_scope() as session:
            row = session.get(ToolInvocationRecord, invocation_id)
            return self._request(row), row.status

    def execution(self, invocation_id):
        with session_scope() as session:
            row = session.get(ToolInvocationRecord, invocation_id)
            request = self._request(row)
            actor = self._actor(session, request.project_id, row.input_payload.get("confirmed_actor_id"))
            return request, UserProfile(id=actor.user_id, name=actor.display_name, email=actor.email, role=actor.role)

    def claim_lease(self, project_id, invocation_id, owner_id):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, project_id)
            command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
            request = self._request(command)
            if request.project_id != project_id or command.status != "running":
                raise GenerationLeaseLost("native build command is already terminal or belongs elsewhere")
            now = session.scalar(select(func.clock_timestamp()))
            row = session.get(Lease, invocation_id)
            digest = self._digest(command)
            if row is not None and (row.project_id != project_id or row.request_digest != digest):
                raise ValueError("native build lease cannot be rebound")
            if row is not None and row.expires_at > now:
                raise GenerationLeaseBusy("another worker owns the native build")
            value = GenerationWorkLease(project_id, invocation_id, owner_id, row.epoch + 1 if row else 1, digest)
            if row is None:
                row = Lease(invocation_id=invocation_id, project_id=project_id)
                session.add(row)
            row.owner_id, row.epoch, row.request_digest = owner_id, value.epoch, digest
            row.acquired_at = row.renewed_at = now
            row.expires_at = now + timedelta(seconds=GENERATION_LEASE_SECONDS)
            return value

    def require_lease(self, lease):
        with session_scope() as session:
            command = session.get(ToolInvocationRecord, lease.invocation_id)
            self._lease(session, command, lease)
            self._request(command)

    def renew_lease(self, lease):
        with session_scope() as session:
            session.scalar(select(Lease).where(Lease.invocation_id == lease.invocation_id).with_for_update())
            row = self._lease(session, session.get(ToolInvocationRecord, lease.invocation_id), lease)
            row.renewed_at = session.scalar(select(func.clock_timestamp()))
            row.expires_at = row.renewed_at + timedelta(seconds=GENERATION_LEASE_SECONDS)

    def release_lease(self, lease):
        with session_scope() as session:
            row = session.scalar(select(Lease).where(Lease.invocation_id == lease.invocation_id).with_for_update())
            if row and (row.project_id, row.owner_id, row.epoch) == (lease.project_id, lease.owner_id, lease.epoch):
                row.expires_at = session.scalar(select(func.clock_timestamp()))

    def reserve(self, request, source, policy, *, actor_id, invocation_id, lease, require_current):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            command = self._canonical(session, request, invocation_id, actor_id)
            self._lease(session, command, lease)
            if session.get(Reservation, invocation_id) is not None:
                raise NativeBuildOutcomeUnknown("native build already reserved; no duplicate execution")
            self._source(session, request, source)
            if snapshot_digest(policy) != request.operator_policy_digest:
                raise ValueError("native build operator confirmation differs")
            require_current()
            pin = source["pin"]
            fields = {"invocation_id": invocation_id, "project_id": request.project_id,
                "build_id": str(uuid5(NAMESPACE_URL, "nasus:native-build:" + invocation_id)),
                "image_revision_id": request.image_revision_id, "manifest_id": pin["manifest_id"],
                "binding_id": request.binding_id, "source_revision_id": request.source_revision_id,
                "actor_id": actor_id, "worker_owner": lease.owner_id, "worker_epoch": lease.epoch,
                "request_hash": snapshot_digest(request.model_dump(mode="json")),
                "recorded_at": datetime.now(timezone.utc).isoformat()}
            payload = {**fields, "request": request.model_dump(mode="json"), "source_pin": pin,
                "source_inventory_digest": snapshot_digest(source["files"]), "operator_policy": policy}
            session.add(Reservation(**fields, payload=payload, content_hash=snapshot_digest(payload)))
            session.flush()
            self._event(session, command, "quality.native_build.reserved", {"build_id": fields["build_id"]})
            return payload

    def commit(self, request, saved, receipt, *, invocation_id, lease, require_current):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            state = self._inspection(session, request.project_id, invocation_id)
            reserved = state["reservation"]
            if reserved is None:
                raise ValueError("native build result has no reservation")
            command = self._canonical(session, request, invocation_id, reserved["actor_id"])
            self._lease(session, command, lease)
            if (reserved["worker_owner"], reserved["worker_epoch"]) != (lease.owner_id, lease.epoch):
                raise GenerationLeaseLost("replacement workers cannot commit an old native attempt")
            if state["result"] is not None:
                require_current()
                return state["result"]
            if (saved.get("build_id") != reserved["build_id"] or saved.get("request_digest") != request.request_digest
                    or receipt.get("request_digest") != request.request_digest or receipt["source"]["pin"] != reserved["source_pin"]
                    or receipt.get("native_build_verified") is not True or receipt.get("execution_authorized") is not False
                    or receipt.get("executed_on_target_count") != 0 or receipt.get("passed_count") != 0
                    or receipt["toolchain"]["image_id"] != reserved["operator_policy"]["image_id"]):
                raise ValueError("native build result differs from its exact reservation")
            require_current()
            fields = {"invocation_id": invocation_id, "project_id": request.project_id, "build_id": reserved["build_id"],
                "artifact_ref": saved["artifact_ref"], "artifact_hash": saved["artifact_hash"],
                "receipt_digest": snapshot_digest(receipt), "recorded_at": datetime.now(timezone.utc).isoformat()}
            payload = {**fields, "request_digest": request.request_digest, "artifact": receipt["artifact"],
                "runtime_library_count": receipt["runtime_inventory"]["runtime_library_count"],
                "compiled_class_count": receipt["runtime_inventory"]["compiled_class_count"], "execution_authorized": False}
            session.add(Result(**fields, payload=payload, content_hash=snapshot_digest(payload)))
            session.flush()
            self._event(session, command, "quality.native_build.archived", {"build_id": reserved["build_id"],
                "receipt_digest": payload["receipt_digest"], "execution_authorized": False})
            return payload

    def finish(self, project_id, invocation_id, status, *, lease=None, control_id=None, actor_id=None, require_current=None):
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError("invalid native build terminal status")
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, project_id)
            command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
            if self._request(command).project_id != project_id:
                raise PermissionError("native build termination project differs")
            work = session.get(Lease, invocation_id)
            if control_id is not None:
                control = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == control_id).with_for_update())
                if (control is None or control.tool_id != NATIVE_BUILD_CANCEL_TOOL or control.status != "running"
                        or control.input_payload.get("confirmed_by_user") is not True
                        or control.input_payload.get("confirmed_actor_id") != actor_id or status != "cancelled"
                        or NativeBuildTarget.model_validate({k: v for k, v in query_payload(control.input_payload).items()
                            if k not in {"confirmed_by_user", "confirmed_at"}}) != NativeBuildTarget(project_id=project_id, invocation_id=invocation_id)):
                    raise ValueError("native build cancellation requires its independent confirmed command")
                self._actor(session, project_id, actor_id)
                TestDesignResultRepository._project_scope(session, control, project_id)
                try:
                    confirmed = datetime.fromisoformat(str(control.input_payload.get("confirmed_at", "")))
                    fresh = confirmed.tzinfo is not None and 0 <= (datetime.now(timezone.utc) - confirmed).total_seconds() <= 900
                except (ValueError, OverflowError):
                    fresh = False
                if not fresh:
                    raise ValueError("native build cancellation requires fresh confirmation")
                require_current()
            elif command.status == "running":
                if lease is not None:
                    self._lease(session, command, lease)
                elif work is not None and work.expires_at > session.scalar(select(func.clock_timestamp())):
                    raise GenerationLeaseBusy("native build is owned by a current worker")
            result = self._value(session.get(Result, invocation_id))
            if command.status == "running":
                if result is not None:
                    status = "completed"
                elif status == "completed":
                    raise ValueError("native build cannot complete without its original result")
                command.status, command.summary = status, ("Native build archived; target execution remains unauthorized." if status == "completed"
                    else "Native build ended without a committed result. Reserved attempts are never automatically rebuilt.")
                command.revision += 1
                command.result_payload = ToolResult(invocation_id=invocation_id, status=status, summary=command.summary,
                    object_refs=["native_build:" + result["build_id"]] if result else []).model_dump()
                self._event(session, command, "tool.invocation.updated", {"status": status, "tool_id": NATIVE_BUILD_TOOL})
            if command.status == "cancelled" and session.get(Cancellation, invocation_id) is None:
                session.add(Cancellation(invocation_id=invocation_id, project_id=project_id, requested_at=datetime.now(timezone.utc)))
                self._event(session, command, "quality.native_build.cancel_requested", {})
            if command.status != "running" and work is not None:
                work.expires_at = session.scalar(select(func.clock_timestamp()))
            return command.status

    def pending(self, *, after_id=None, limit=100):
        with session_scope() as session:
            query = select(ToolInvocationRecord).where(ToolInvocationRecord.tool_id == NATIVE_BUILD_TOOL,
                ToolInvocationRecord.status == "running")
            if after_id:
                query = query.where(ToolInvocationRecord.id > after_id)
            return [(row.id, row.input_payload.get("project_id")) for row in session.scalars(
                query.order_by(ToolInvocationRecord.id).limit(min(max(limit, 1), 100)))]

    def pending_cancellations(self, *, after_id=None, limit=100):
        with session_scope() as session:
            query = select(Cancellation).where(Cancellation.delivered_at.is_(None))
            if after_id:
                query = query.where(Cancellation.invocation_id > after_id)
            return [(row.invocation_id, row.project_id) for row in session.scalars(
                query.order_by(Cancellation.invocation_id).limit(min(max(limit, 1), 100)))]

    def cancellation_delivered(self, project_id, invocation_id):
        with session_scope() as session:
            row = session.scalar(select(Cancellation).where(Cancellation.invocation_id == invocation_id).with_for_update())
            command = session.get(ToolInvocationRecord, invocation_id)
            if row is None or row.project_id != project_id or command is None or command.status != "cancelled":
                raise ValueError("native build cancellation delivery differs")
            if row.delivered_at is None:
                row.delivered_at = datetime.now(timezone.utc)
                self._event(session, command, "quality.native_build.cancel_delivered", {})

    @staticmethod
    def _event(session, command, kind, patch):
        project_id, now = command.input_payload["project_id"], datetime.now(timezone.utc).isoformat()
        session.add(AuditEventRecord(id=str(uuid4()), occurred_at=now, actor=command.input_payload["confirmed_actor_id"],
            actor_kind="user", action=kind, entity_type="tool_invocation", entity_id=command.id,
            status=command.status, summary="Native build lifecycle; no target execution authority.",
            conversation_id=command.conversation_id, tool_invocation_id=command.id,
            agent_goal_id=command.input_payload.get("agent_goal_id"), object_refs=[], evidence_refs=[], event_metadata=patch))
        EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=kind, occurred_at=now,
            correlation_id=project_id, entity_type="tool_invocation", entity_id=command.id,
            conversation_id=command.conversation_id, agent_goal_id=command.input_payload.get("agent_goal_id"),
            entity_version=command.revision, mutation_kind="replace" if kind == "tool.invocation.updated" else "append",
            patch={"project_id": project_id, **patch}, query_keys=[["native-build", project_id, command.id],
                ["tool-invocation", command.id]], snapshot_hint=True), session=session)
