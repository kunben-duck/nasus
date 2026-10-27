"""PG-clock ownership and original command fences for once-only case dispatch."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.run_plan_case_execution import (
    CASE_CLAIM_SCHEMA, CASE_OUTCOME_SCHEMA, CASE_CANCEL_TOOL, CASE_LEASE_SECONDS,
    RunPlanCaseExecutionInvalid, RunPlanCaseWorkBusy, RunPlanCaseWorkLost, RunPlanCaseAlreadyClaimed,
    restore_case_scope, case_work_schema, RunPlanCaseLease, case_claim_id, execution_state, verify_original_case_command,
)
from .db_models import AuditEventRecord, ToolInvocationRecord, UserIdentityRecord, ProjectRoleBindingRecord
from .event_outbox_repository import EventOutboxRepository
from .run_plan_case_execution_models import (
    RunPlanCaseWorkRecord as Work, RunPlanCaseLeaseRecord as Lease, RunPlanCaseClaimRecord as Claim,
    RunPlanCaseOutcomeRecord as Outcome, RunPlanCaseCancellationRecord as Cancellation,
)
from .test_design_scope_repository import TestDesignScopeRepository
from .run_plan_case_preparation_repository import RunPlanCasePreparationJournal
from .run_plan_case_cancellation_journal import RunPlanCaseCancellationJournal
from .unit_of_work import session_scope


class PostgresRunPlanCaseExecutionRepository:
    def original_command(self, project_id, invocation_id, *, actor_id, require_current):
        require_current()
        with session_scope() as session:
            def snapshot():
                command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
                    .execution_options(populate_existing=True))
                if (command is None or type(command.input_payload) is not dict
                        or command.input_payload.get("project_id") != project_id):
                    raise RunPlanCaseExecutionInvalid("case producer requires an original command in this project")
                RunPlanCasePreparationJournal.verify(session, command)
                return deepcopy({key: getattr(command, key) for key in ("id", "tool_id", "status", "input_payload")})

            self._actor(session, project_id, actor_id)
            snapshot()
            require_current()
            self._actor(session, project_id, actor_id)
            # Reauthorization can outlive consent or observe a cancellation.
            # Never return the command or PG clock sampled before that callback.
            command = snapshot()
            return {"command": command, "now": session.scalar(select(func.clock_timestamp()))}
    @staticmethod
    def _actor(session, project_id, actor_id):
        actor = session.scalar(select(UserIdentityRecord).where(UserIdentityRecord.user_id == actor_id)
            .execution_options(populate_existing=True))
        roles = session.scalars(select(ProjectRoleBindingRecord).where(
            ProjectRoleBindingRecord.project_id == project_id, ProjectRoleBindingRecord.user_id == actor_id,
            ProjectRoleBindingRecord.version_id.is_(None), ProjectRoleBindingRecord.session_id.is_(None),
            ProjectRoleBindingRecord.status == "active").execution_options(populate_existing=True)).all()
        if (actor is None or actor.status != "active" or (actor.role != "platform_admin"
                and (len(roles) != 1 or roles[0].role not in {"qa_lead", "project_admin"}))):
            raise PermissionError("case work requires a current independent execution role")

    @staticmethod
    def _command(session, scope, *, historical=False):
        query = select(ToolInvocationRecord).where(ToolInvocationRecord.id == scope.invocation_id)
        command = session.scalar((query if historical else query.with_for_update()).execution_options(populate_existing=True))
        if command is None or type(command.input_payload) is not dict:
            raise RunPlanCaseExecutionInvalid("original independent case command is missing")
        selection = {key: value for key, value in query_payload(command.input_payload).items()
            if key not in {"confirmed_by_user", "confirmed_at"}}
        snapshot = {key: getattr(command, key) for key in ("id", "tool_id", "status", "input_payload")}
        verify_original_case_command(scope, snapshot, selection, historical=historical,
            now=session.scalar(select(func.clock_timestamp())) if not historical else None)
        RunPlanCasePreparationJournal.verify(session, command)
        return command

    @staticmethod
    def _work_value(scope, roster, recorded_at):
        pins = {key: getattr(scope, key) for key in ("project_id", "run_id", "invocation_id", "actor_id", "run_plan_id",
            "run_plan_artifact_hash", "plan_digest", "image_revision_id", "manifest_id")}
        return {"schema": case_work_schema(scope), "work_id": scope.work_id, **pins,
            "scope_digest": scope.digest, "roster_digest": acceptance_digest(roster), "scope": asdict(scope),
            "roster": deepcopy(list(roster)), "recorded_at": recorded_at}

    @classmethod
    def _work(cls, session, scope, roster):
        row = session.get(Work, scope.work_id)
        if row is None:
            raise RunPlanCaseExecutionInvalid("original case work is missing; never manufacture historical inputs")
        value = cls._work_value(scope, roster, row.recorded_at)
        columns = set(row.__table__.columns.keys()) - {"content_hash"}
        if (acceptance_digest(value) != row.content_hash
                or acceptance_digest({key: value[key] for key in columns}) !=
                    acceptance_digest({key: getattr(row, key) for key in columns})):
            raise RunPlanCaseExecutionInvalid("case work cannot change its original complete scope or roster")
        return row

    @staticmethod
    def _payload(row, schema):
        if row is None:
            return None
        value = row.payload
        columns = set(row.__table__.columns.keys()) - {"payload", "content_hash"}
        if (type(value) is not dict or value.get("schema") != schema
                or acceptance_digest(value) != row.content_hash
                or acceptance_digest({key: value.get(key) for key in columns}) !=
                    acceptance_digest({key: getattr(row, key) for key in columns})):
            raise RunPlanCaseExecutionInvalid("original case fact columns and immutable payload differ")
        return deepcopy(value)

    @staticmethod
    def _row(model, value):
        columns = set(model.__table__.columns.keys()) - {"payload", "content_hash"}
        return model(**{key: value[key] for key in columns}, payload=deepcopy(value), content_hash=acceptance_digest(value))

    @staticmethod
    def _event(session, scope, value, event_type):
        recorded_at = value["recorded_at"]
        summary = "Original RunPlan case journal; not verified business coverage or release evidence."
        session.add(AuditEventRecord(id=str(uuid4()), occurred_at=recorded_at, actor=value.get("actor_id", scope.actor_id),
            actor_kind="user", action=event_type, entity_type="run_plan_case_work", entity_id=scope.work_id,
            status=value.get("status", "recorded"), summary=summary, tool_invocation_id=scope.invocation_id,
            object_refs=[], evidence_refs=[], event_metadata={"business_coverage_verified": False}))
        # Shared views never receive command inputs, private wire bytes or storage refs.
        EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=event_type,
            occurred_at=recorded_at, correlation_id=scope.project_id, entity_type="run_plan_case_work",
            entity_id=scope.work_id, entity_version=1, mutation_kind="append",
            patch={"project_id": scope.project_id, "invocation_id": scope.invocation_id,
                "status": value.get("status", "recorded")}, query_keys=[["run-plan-case-work", scope.project_id]],
            snapshot_hint=True), session=session)

    @classmethod
    def _cancelled(cls, session, scope):
        original = session.get(ToolInvocationRecord, scope.invocation_id)
        lifecycle = RunPlanCaseCancellationJournal.verify(session, original) if original is not None else None
        value = cls._payload(session.get(Cancellation, scope.work_id), "nasus.run-plan-case-cancellation.v1")
        if lifecycle is not None and value is not None:
            raise RunPlanCaseExecutionInvalid("case cancellation cannot adopt two different command protocols")
        if (original is not None and original.status == "cancelled" and original.input_payload.get("case_claim_protocol") is not None
                and lifecycle is None and value is None):
            raise RunPlanCaseExecutionInvalid("original case cancellation lost its confirmed immutable request")
        if value is not None:
            fields = {"schema", "work_id", "project_id", "control_id", "actor_id", "recorded_at", "scope_digest", "status",
                "control_digest"}
            if (set(value) != fields or value.get("scope_digest") != scope.digest or value.get("project_id") != scope.project_id
                    or value.get("work_id") != scope.work_id or value.get("status") != "cancelled"):
                raise RunPlanCaseExecutionInvalid("original case cancellation was rebound")
            control = session.get(ToolInvocationRecord, value["control_id"])
            request = {"project_id": scope.project_id, "invocation_id": scope.invocation_id, "scope_digest": scope.digest}
            if (control is None or type(control.input_payload) is not dict or control.tool_id != CASE_CANCEL_TOOL
                    or control.status not in {"running", "completed", "failed", "cancelled"}
                    or control.input_payload.get("confirmed_by_user") is not True
                    or control.input_payload.get("confirmed_actor_id") != value["actor_id"]
                    or {key: item for key, item in query_payload(control.input_payload).items()
                        if key not in {"confirmed_by_user", "confirmed_at"}} != request
                    or acceptance_digest({"tool_id": control.tool_id, "input_payload": control.input_payload}) != value["control_digest"]):
                raise RunPlanCaseExecutionInvalid("original case cancellation lost its independent control ancestry")
        return value is not None or lifecycle is not None

    @classmethod
    def _live(cls, session, lease, *, require_current):
        require_current()
        scope = restore_case_scope(asdict(lease.scope))
        cls._command(session, scope)
        cls._actor(session, scope.project_id, scope.actor_id)
        row = session.scalar(select(Lease).where(Lease.work_id == scope.work_id).with_for_update()
            .execution_options(populate_existing=True))
        if cls._cancelled(session, scope):
            raise RunPlanCaseWorkLost("original case command was independently cancelled")
        require_current()
        cls._command(session, scope)
        cls._actor(session, scope.project_id, scope.actor_id)
        now = session.scalar(select(func.clock_timestamp()))
        if (row is None or row.project_id != scope.project_id or row.owner_id != lease.owner_id
                or type(row.epoch) is not int or row.epoch != lease.epoch or row.expires_at <= now
                or not row.acquired_at <= row.renewed_at <= now < row.expires_at
                or row.expires_at - row.renewed_at != timedelta(seconds=CASE_LEASE_SECONDS)):
            raise RunPlanCaseWorkLost("case worker lost its original live PostgreSQL lease")
        return row, now

    def acquire(self, scope, roster, owner_id, *, require_current):
        scope = restore_case_scope(asdict(scope))
        RunPlanCaseLease(scope, owner_id, 1)
        execution_state(scope, roster, [], [], cancelled=False)
        require_current()
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, scope.project_id)
            self._command(session, scope)
            self._actor(session, scope.project_id, scope.actor_id)
            work = session.get(Work, scope.work_id)
            if work is not None:
                self._work(session, scope, roster)
            if self._cancelled(session, scope):
                raise RunPlanCaseWorkLost("cancelled original case work cannot acquire another worker")
            row = session.scalar(select(Lease).where(Lease.work_id == scope.work_id).with_for_update())
            if (work is None) != (row is None):
                raise RunPlanCaseExecutionInvalid("original work/lease pair is incomplete; never repair history")
            require_current()
            command = self._command(session, scope)
            self._actor(session, scope.project_id, scope.actor_id)
            now = session.scalar(select(func.clock_timestamp()))
            if row is not None and row.expires_at > now:
                raise RunPlanCaseWorkBusy("another worker owns the original complete case attempt")
            if work is None:
                preparation = RunPlanCasePreparationJournal.verify(session, command)
                value = self._work_value(scope, roster, now.isoformat())
                session.add(Work(**{key: value[key] for key in Work.__table__.columns.keys() if key != "content_hash"},
                    content_hash=acceptance_digest(value)))
                session.flush()
                RunPlanCasePreparationJournal.bind(session, command, preparation, value)
                self._event(session, scope, value, "quality.run_plan.case_work_recorded")
            epoch = row.epoch + 1 if row else 1
            lease = RunPlanCaseLease(scope, owner_id, epoch)
            if row is None:
                row = Lease(work_id=scope.work_id, project_id=scope.project_id)
                session.add(row)
            row.owner_id, row.epoch = owner_id, epoch
            row.acquired_at = row.renewed_at = now
            row.expires_at = now + timedelta(seconds=CASE_LEASE_SECONDS)
            session.flush()
            self._live(session, lease, require_current=require_current)
            return lease

    def require(self, lease, *, require_current):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, lease.scope.project_id)
            work = session.get(Work, lease.work_id)
            if work is None:
                raise RunPlanCaseWorkLost("original case work is missing")
            self._work(session, lease.scope, tuple(work.roster))
            self._live(session, lease, require_current=require_current)

    def renew(self, lease, *, require_current):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, lease.scope.project_id)
            work = session.get(Work, lease.work_id)
            if work is None:
                raise RunPlanCaseWorkLost("original case work is missing")
            self._work(session, lease.scope, tuple(work.roster))
            row, now = self._live(session, lease, require_current=require_current)
            row.renewed_at, row.expires_at = now, now + timedelta(seconds=CASE_LEASE_SECONDS)
            session.flush()
            self._live(session, lease, require_current=require_current)

    def inspect(self, scope, roster, *, require_access):
        require_access()
        with session_scope() as session:
            self._command(session, scope, historical=True)
            self._work(session, scope, roster)
            lease = session.get(Lease, scope.work_id)
            if lease is None or lease.project_id != scope.project_id or type(lease.epoch) is not int or not 1 <= lease.epoch <= 2147483647:
                raise RunPlanCaseExecutionInvalid("original case ownership is missing or cannot be verified")
            claims = [self._payload(row, CASE_CLAIM_SCHEMA) for row in session.scalars(select(Claim)
                .where(Claim.work_id == scope.work_id).order_by(Claim.ordinal)).all()]
            outcomes = [self._payload(row, CASE_OUTCOME_SCHEMA) for row in session.scalars(select(Outcome)
                .join(Claim, Outcome.claim_id == Claim.claim_id).where(Claim.work_id == scope.work_id)
                .order_by(Claim.ordinal)).all()]
            cancelled = self._cancelled(session, scope)
            execution_state(scope, roster, claims, outcomes, cancelled=cancelled)
            if any(item["epoch"] > lease.epoch for item in claims):
                raise RunPlanCaseExecutionInvalid("original dispatch cannot have a future ownership epoch")
            require_access()
            return {"claims": claims, "outcomes": outcomes, "cancelled": cancelled}

    def claim(self, lease, case, *, require_current):
        scope = lease.scope
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, scope.project_id)
            work = session.get(Work, scope.work_id)
            if work is None:
                raise RunPlanCaseExecutionInvalid("original case work is missing")
            roster = tuple(work.roster)
            self._work(session, scope, roster)
            if case not in roster:
                raise RunPlanCaseExecutionInvalid("case claim is outside the complete original roster")
            _, now = self._live(session, lease, require_current=require_current)
            claim_id = case_claim_id(scope, case["case_id"])
            if session.get(Claim, claim_id) is not None:
                raise RunPlanCaseAlreadyClaimed("original case already has a durable dispatch; never resend")
            value = {"schema": CASE_CLAIM_SCHEMA, "claim_id": claim_id, "project_id": scope.project_id,
                "work_id": scope.work_id, **deepcopy(case), "scope_digest": scope.digest,
                "owner_id": lease.owner_id, "epoch": lease.epoch, "recorded_at": now.isoformat()}
            execution_state(scope, roster, [value], [], cancelled=False)
            session.add(self._row(Claim, value))
            self._event(session, scope, value, "quality.run_plan.case_dispatch_reserved")
            session.flush()
            self._live(session, lease, require_current=require_current)
            return value

    def complete(self, lease, claim, *, artifact_ref, artifact_hash, observation, require_current):
        scope = lease.scope
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, scope.project_id)
            work = session.get(Work, scope.work_id)
            if work is None:
                raise RunPlanCaseExecutionInvalid("original case work is missing")
            roster = tuple(work.roster)
            self._work(session, scope, roster)
            _, now = self._live(session, lease, require_current=require_current)
            original = self._payload(session.get(Claim, claim["claim_id"]), CASE_CLAIM_SCHEMA)
            if original != claim or (original["owner_id"], original["epoch"]) != (lease.owner_id, lease.epoch):
                raise RunPlanCaseWorkLost("late worker cannot commit a different owner's original case output")
            if (observation.get("project_id") != scope.project_id or observation.get("plan_digest") != scope.plan_digest
                    or observation.get("run_id") != scope.run_id or observation.get("case_id") != original["case_id"]
                    or observation.get("case_digest") != original["case_digest"]):
                raise RunPlanCaseExecutionInvalid("case result must retain its complete original plan and case")
            value = {"schema": CASE_OUTCOME_SCHEMA, "project_id": scope.project_id, "claim_id": claim["claim_id"],
                "case_id": claim["case_id"], "dispatch_digest": acceptance_digest(claim), "recorded_at": now.isoformat(),
                "status": observation["status"], "observation_digest": observation["observation_digest"],
                "artifact_ref": artifact_ref, "artifact_hash": artifact_hash}
            execution_state(scope, roster, [claim], [value], cancelled=False)
            prior = self._payload(session.get(Outcome, claim["claim_id"]), CASE_OUTCOME_SCHEMA)
            if prior is not None:
                if any(prior[key] != value[key] for key in value if key != "recorded_at"):
                    raise RunPlanCaseExecutionInvalid("committed original case output cannot be replaced")
                self._live(session, lease, require_current=require_current)
                return prior
            session.add(self._row(Outcome, value))
            self._event(session, scope, value, "quality.run_plan.case_output_recorded")
            session.flush()
            self._live(session, lease, require_current=require_current)
            return value

    def cancel(self, scope, roster, *, control_id, actor_id, require_current):
        """Independent original cancellation, not a statement that the target rolled back."""
        require_current()
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, scope.project_id)
            self._command(session, scope, historical=True)
            self._work(session, scope, roster)
            self._actor(session, scope.project_id, actor_id)
            command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == control_id).with_for_update())
            now = session.scalar(select(func.clock_timestamp()))
            request = {"project_id": scope.project_id, "invocation_id": scope.invocation_id, "scope_digest": scope.digest}
            if (command is None or type(command.input_payload) is not dict
                    or command.tool_id != CASE_CANCEL_TOOL or command.status != "running"
                    or command.input_payload.get("confirmed_by_user") is not True
                    or command.input_payload.get("confirmed_actor_id") != actor_id
                    or {key: value for key, value in query_payload(command.input_payload).items()
                        if key not in {"confirmed_by_user", "confirmed_at"}} != request):
                raise RunPlanCaseExecutionInvalid("case cancellation needs its exact independent confirmed control")
            confirmed = datetime.fromisoformat(command.input_payload["confirmed_at"])
            if confirmed.tzinfo is None or not 0 <= (now - confirmed).total_seconds() <= 900:
                raise RunPlanCaseExecutionInvalid("case cancellation consent expired")
            require_current()
            prior = self._payload(session.get(Cancellation, scope.work_id), "nasus.run-plan-case-cancellation.v1")
            if prior is not None:
                if prior["control_id"] != control_id or prior["scope_digest"] != scope.digest:
                    raise RunPlanCaseExecutionInvalid("case cancellation cannot replace the original control")
                return prior
            value = {"schema": "nasus.run-plan-case-cancellation.v1", "work_id": scope.work_id,
                "project_id": scope.project_id, "actor_id": actor_id, "control_id": control_id,
                "scope_digest": scope.digest, "recorded_at": now.isoformat(), "status": "cancelled",
                "control_digest": acceptance_digest({"tool_id": command.tool_id, "input_payload": command.input_payload})}
            session.add(self._row(Cancellation, value))
            self._event(session, scope, value, "quality.run_plan.case_cancellation_recorded")
            session.flush()
            return value
