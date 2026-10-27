"""Canonical commands are durable dispatch intents, not a second lifecycle."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased

from ...application.platform.account_models import UserProfile
from ...application.platform.tool_models import EventPayload, ToolResult
from ...application.platform.tool_handlers.query_input import query_payload
from ...application.quality_loop.generation_job_ports import GENERATION_RECOVER_TOOL, GENERATION_CANCEL_TOOL, GenerationRecoveryRequest, parse_generation_recovery, GenerationJobTarget, GenerationHistoryRequest
from ...application.quality_loop.test_design_results import GENERATION_TOOL, GenerationResultRequest, TestDesignResultIntegrityError
from ...application.quality_loop.generation_work_lease import (
    GENERATION_LEASE_SECONDS, GenerationLeaseBusy, GenerationLeaseLost, GenerationWorkLease,
)
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from .db_models import ToolInvocationRecord, UserIdentityRecord, AuditEventRecord
from .event_outbox_repository import EventOutboxRepository
from .generation_job_models import GenerationJobCancellationRecord as Cancellation, GenerationWorkLeaseRecord as WorkLease
from .test_design_result_models import TestDesignResultRecord as Result
from .test_design_result_repository import TestDesignResultRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .unit_of_work import session_scope

JOB_TOOLS = (GENERATION_TOOL, GENERATION_RECOVER_TOOL)


class GenerationJobRepository:
    @staticmethod
    def _request_digest(command):
        return acceptance_digest({"tool_id": command.tool_id, "input_payload": command.input_payload})

    @classmethod
    def _require_lease_state(cls, session, command, lease, *, now=None):
        # Heartbeats can commit while a business transaction validates its
        # inputs. Do not fence that transaction against an identity-map copy.
        row = session.scalar(select(WorkLease).where(WorkLease.invocation_id == lease.invocation_id)
            .execution_options(populate_existing=True))
        now = now or session.scalar(select(func.clock_timestamp()))
        if (command is None or command.id != lease.invocation_id or command.status != "running"
                or command.input_payload.get("project_id") != lease.project_id
                or row is None or row.project_id != lease.project_id or row.owner_id != lease.owner_id
                or row.epoch != lease.epoch or row.expires_at <= now
                or row.request_digest != lease.request_digest or cls._request_digest(command) != lease.request_digest):
            raise GenerationLeaseLost("generation worker no longer owns the current command")
        return row

    @classmethod
    def _require_lease(cls, session, command, lease, *, now=None):
        row = cls._require_lease_state(session, command, lease, now=now)
        cls._request(command)
        return row

    def claim_lease(self, project_id, invocation_id, owner_id):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, project_id)
            command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
            request = self._request(command)
            if request.project_id != project_id:
                raise TestDesignResultIntegrityError("generation lease project mismatch")
            if command.status != "running":
                raise GenerationLeaseLost("generation command is already terminal")
            now = session.scalar(select(func.clock_timestamp()))
            row = session.get(WorkLease, invocation_id)
            if row is not None and (row.project_id != project_id or row.request_digest != self._request_digest(command)):
                raise TestDesignResultIntegrityError("generation lease cannot be rebound to changed canonical input")
            if row is not None and row.expires_at > now:
                raise GenerationLeaseBusy("another worker owns the running generation; retry without changing its status")
            lease = GenerationWorkLease(project_id, invocation_id, owner_id, row.epoch + 1 if row else 1, self._request_digest(command))
            if row is None:
                row = WorkLease(invocation_id=invocation_id, project_id=project_id)
                session.add(row)
            row.owner_id, row.epoch, row.request_digest = owner_id, lease.epoch, lease.request_digest
            row.acquired_at = row.renewed_at = now
            row.expires_at = now + timedelta(seconds=GENERATION_LEASE_SECONDS)
            session.flush()
            return lease

    def require_lease(self, lease):
        # Read-only: also called inside a project-locked business transaction.
        # Acquiring that lock on a second connection would deadlock the writer.
        with session_scope() as session:
            self._require_lease(session, session.get(ToolInvocationRecord, lease.invocation_id), lease)

    def renew_lease(self, lease):
        with session_scope() as session:
            # Only serialize heartbeat ownership. Business validation holds the
            # project/command locks; taking either here would starve renewal.
            session.scalar(select(WorkLease).where(WorkLease.invocation_id == lease.invocation_id).with_for_update())
            command = session.get(ToolInvocationRecord, lease.invocation_id)
            now = session.scalar(select(func.clock_timestamp()))
            row = self._require_lease(session, command, lease, now=now)
            row.renewed_at, row.expires_at = now, now + timedelta(seconds=GENERATION_LEASE_SECONDS)

    def release_lease(self, lease):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, lease.project_id)
            row = session.get(WorkLease, lease.invocation_id)
            if row and row.project_id == lease.project_id and row.owner_id == lease.owner_id and row.epoch == lease.epoch:
                row.expires_at = session.scalar(select(func.clock_timestamp()))

    def history(self, request):
        request = GenerationHistoryRequest.model_validate(request.model_dump(mode="json"))
        command, source = ToolInvocationRecord, aliased(ToolInvocationRecord)

        def matches(row):
            payload = row.input_payload
            return and_(row.tool_id == GENERATION_TOOL, payload["project_id"].as_string() == request.project_id,
                payload["scope_revision_id"].as_string() == request.scope_revision_id,
                payload["scope_artifact_hash"].as_string() == request.scope_artifact_hash,
                payload["confirmed_by_user"].as_boolean().is_(True),
                payload["execution"]["plan_digest"].as_string().is_not(None))

        query = select(command, source).outerjoin(source, and_(command.tool_id == GENERATION_RECOVER_TOOL,
            source.id == command.input_payload["invocation_id"].as_string())).where(
                command.status.in_(("running", "completed", "failed", "cancelled")),
                or_(matches(command), and_(command.tool_id == GENERATION_RECOVER_TOOL, matches(source),
                    command.input_payload["project_id"].as_string() == request.project_id,
                    command.input_payload["confirmed_by_user"].as_boolean().is_(True))))
        with session_scope() as session:
            # Running is checked over the full matching scope, not just this page.
            has_running = session.scalar(select(query.where(command.status == "running").exists()))
            rows = session.execute(query.where(command.id > request.after_id).order_by(command.id).limit(request.limit + 1)).all()
            items = []
            for row, original in rows[:request.limit]:
                self._request(row)
                original = original if row.tool_id == GENERATION_RECOVER_TOOL else row
                items.append({"invocation_id": row.id, "source_invocation_id": original.id,
                    "tool_id": row.tool_id, "status": row.status, "source_request": self._request(original)})
            return {"commands": items, "has_running": has_running,
                "next_after_id": items[-1]["invocation_id"] if len(rows) > request.limit else None}

    @staticmethod
    def _request(row):
        if (row is None or row.tool_id not in JOB_TOOLS or not isinstance(row.input_payload, dict)
                or row.input_payload.get("confirmed_by_user") is not True):
            raise TestDesignResultIntegrityError("generation job requires a confirmed canonical command")
        try:
            value = {k: v for k, v in query_payload(row.input_payload).items()
                if k not in {"confirmed_by_user", "confirmed_at"}}
            return (GenerationResultRequest.model_validate(value) if row.tool_id == GENERATION_TOOL
                else parse_generation_recovery(value))
        except (ValueError, TypeError) as exc:
            raise TestDesignResultIntegrityError("generation job command could not be verified") from exc

    def command(self, invocation_id):
        with session_scope() as session:
            row = session.get(ToolInvocationRecord, invocation_id)
            return self._request(row), row.status

    def execution(self, invocation_id):
        request, source, actor_id = self.inspection(invocation_id)
        with session_scope() as session:
            actor = session.get(UserIdentityRecord, actor_id)
            if actor is None or actor.status != "active":
                raise PermissionError("generation confirming account is unavailable")
            return request, source, UserProfile(id=actor.user_id, name=actor.display_name, email=actor.email, role=actor.role)

    def inspection(self, invocation_id):
        with session_scope() as session:
            row = session.get(ToolInvocationRecord, invocation_id)
            request = self._request(row)
            source = request if row.tool_id == GENERATION_TOOL else self._request(session.get(ToolInvocationRecord, request.invocation_id))
            if not isinstance(source, GenerationResultRequest) or source.project_id != request.project_id:
                raise TestDesignResultIntegrityError("generation recovery source command mismatch")
            return request, source, row.input_payload.get("confirmed_actor_id")

    def require_running(self, request, invocation_id, actor_id):
        if not isinstance(request, (GenerationResultRequest, GenerationRecoveryRequest)):
            from ...application.quality_loop.generation_batch_recovery import GenerationBatchRecoveryRequest
            from .generation_batch_recovery_repository import GenerationBatchRecoveryRepository
            if not isinstance(request, GenerationBatchRecoveryRequest):
                raise TestDesignResultIntegrityError("unknown generation recovery contract")
            GenerationBatchRecoveryRepository().require_confirmation(request, invocation_id, actor_id)
            return
        with session_scope() as session:
            if isinstance(request, GenerationRecoveryRequest):
                source = self._request(session.get(ToolInvocationRecord, request.invocation_id))
                TestDesignResultRepository._canonical(session, source, request.invocation_id, actor_id,
                    authority_invocation_id=invocation_id)
            else:
                TestDesignResultRepository._canonical(session, request, invocation_id, actor_id)

    def pending(self, *, after_id=None, limit=100):
        with session_scope() as session:
            query = select(ToolInvocationRecord).where(ToolInvocationRecord.tool_id.in_(JOB_TOOLS), ToolInvocationRecord.status == "running")
            if after_id is not None:
                query = query.where(ToolInvocationRecord.id > after_id)
            return [(row.id, row.input_payload.get("project_id")) for row in session.scalars(
                query.order_by(ToolInvocationRecord.id).limit(min(max(limit, 1), 100)))]

    def pending_cancellations(self, *, after_id=None, limit=100):
        with session_scope() as session:
            query = select(Cancellation).where(Cancellation.delivered_at.is_(None))
            if after_id is not None:
                query = query.where(Cancellation.invocation_id > after_id)
            return [(row.invocation_id, row.project_id) for row in session.scalars(
                query.order_by(Cancellation.invocation_id).limit(min(max(limit, 1), 100)))]

    def cancellation_delivered(self, project_id, invocation_id):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, project_id)
            row = session.get(Cancellation, invocation_id)
            command = session.get(ToolInvocationRecord, invocation_id)
            if (row is None or row.project_id != project_id or command is None or command.tool_id not in JOB_TOOLS
                    or command.status != "cancelled" or command.input_payload.get("project_id") != project_id):
                raise TestDesignResultIntegrityError("generation cancellation receipt mismatch")
            if row.delivered_at is None:
                row.delivered_at = datetime.now(timezone.utc)
                self._event(session, command, "quality.test_design.cancel_delivered", {})

    def finish(self, project_id, invocation_id, status, summary, *, control_id=None, actor_id=None, require_current=None, lease=None):
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError("invalid generation job termination")
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, project_id)
            row = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
            request = self._request(row)
            if request.project_id != project_id:
                raise TestDesignResultIntegrityError("generation job project mismatch")
            work = session.get(WorkLease, invocation_id)
            now = session.scalar(select(func.clock_timestamp()))
            if row.status == "running" and control_id is None:
                if lease is not None:
                    self._require_lease(session, row, lease, now=now)
                elif work is not None and work.expires_at > now:
                    raise GenerationLeaseBusy("cannot terminate a generation owned by a live worker")
            if control_id is not None:
                TestDesignScopeRepository._actor(session, project_id, actor_id)
                control = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == control_id).with_for_update())
                if (status != "cancelled" or control is None or control.tool_id != GENERATION_CANCEL_TOOL
                        or control.status != "running" or control.input_payload.get("confirmed_by_user") is not True
                        or control.input_payload.get("confirmed_actor_id") != actor_id
                        or GenerationJobTarget.model_validate({k: v for k, v in query_payload(control.input_payload).items()
                            if k not in {"confirmed_by_user", "confirmed_at"}}) != GenerationJobTarget(project_id=project_id, invocation_id=invocation_id)):
                    raise TestDesignResultIntegrityError("generation cancellation requires its own canonical authority")
                TestDesignResultRepository._project_scope(session, control, project_id)
                if require_current is None:
                    raise TestDesignResultIntegrityError("generation control requires current administrator authority")
                require_current()
            source_id = invocation_id if isinstance(request, GenerationResultRequest) else request.invocation_id
            result = session.scalar(select(Result).where(Result.invocation_id == source_id))
            if result is not None and source_id != invocation_id and result.payload.get("recovery_invocation_id") != invocation_id:
                # A competing recovery may have committed first. Its result is
                # not completion authority for this independently confirmed job.
                result = None
            if row.status == "running":
                if result is not None:
                    status, summary = "completed", "Draft cases and planned coverage archived; mapping review and target execution remain separate."
                elif status == "completed":
                    raise TestDesignResultIntegrityError("generation cannot complete without its committed result")
                row.status, row.summary = status, summary
                row.revision += 1
                refs = ["test_design_result:" + result.generation_id] if result is not None else []
                row.result_payload = ToolResult(invocation_id=row.id, status=status, summary=summary, object_refs=refs).model_dump()
                session.add(AuditEventRecord(id=str(uuid4()), occurred_at=datetime.now(timezone.utc).isoformat(),
                    actor=row.input_payload["confirmed_actor_id"], actor_kind="user", action="tool.invocation." + status,
                    entity_type="tool_invocation", entity_id=row.id, status=status, summary=summary,
                    conversation_id=row.conversation_id, tool_invocation_id=row.id,
                    agent_goal_id=row.input_payload.get("agent_goal_id"), object_refs=refs, evidence_refs=[], event_metadata={}))
                self._event(session, row, "tool.invocation.updated", {"status": status, "summary": summary, "tool_id": row.tool_id})
            if row.status == "cancelled" and session.get(Cancellation, invocation_id) is None:
                session.add(Cancellation(invocation_id=invocation_id, project_id=project_id, requested_at=datetime.now(timezone.utc)))
                self._event(session, row, "quality.test_design.cancel_requested", {})
            if row.status != "running" and work is not None:
                work.expires_at = now
            return row.status

    @staticmethod
    def _event(session, command, kind, patch):
        EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=kind,
            occurred_at=datetime.now(timezone.utc).isoformat(), correlation_id=command.conversation_id or command.id,
            entity_type="tool_invocation", entity_id=command.id, conversation_id=command.conversation_id,
            agent_goal_id=command.input_payload.get("agent_goal_id"), entity_version=command.revision,
            mutation_kind="replace" if kind == "tool.invocation.updated" else "append", patch=patch,
            query_keys=[["tool-invocation", command.id], ["test-design-job", command.input_payload["project_id"], command.id]]), session=session)
