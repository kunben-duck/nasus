"""ToolInvocation owns lifecycle; immutable preparation/work and native output own evidence."""
from copy import deepcopy
from uuid import uuid4

from sqlalchemy import func, select

from ...application.platform.account_models import UserProfile
from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload, ToolResult
from ...application.quality_loop.run_plan_case_inputs import RunPlanCaseExecutionSelection
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.run_plan_case_execution import (
    CASE_EXECUTE_TOOL, CASE_CLAIM_SCHEMA, CASE_OUTCOME_SCHEMA, RunPlanCaseExecutionInvalid,
    RunPlanCaseWorkBusy, restore_case_scope, execution_state, verify_case_command_selection,
)
from ...domain.quality_loop.run_plan_case_job import CASE_JOB_CANCELLATION_SCHEMA, CASE_JOB_DELIVERY_SCHEMA, verify_case_job_control, verify_case_job_cancellation
from .db_models import ToolInvocationRecord, UserIdentityRecord, AuditEventRecord
from .event_outbox_repository import EventOutboxRepository
from .run_plan_case_preparation_repository import RunPlanCasePreparationJournal as PreparationJournal, RunPlanCasePreparationRepository
from .run_plan_case_cancellation_journal import RunPlanCaseCancellationJournal as CancellationJournal
from .run_plan_case_execution_repository import PostgresRunPlanCaseExecutionRepository as Cases
from .run_plan_case_execution_models import RunPlanCaseWorkRecord as Work, RunPlanCaseLeaseRecord as Lease, RunPlanCaseClaimRecord as Claim, RunPlanCaseOutcomeRecord as Outcome
from .run_plan_case_job_models import RunPlanCaseJobCancellationRecord as Cancellation, RunPlanCaseJobCancellationDeliveryRecord as Delivery
from .test_design_result_repository import TestDesignResultRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .unit_of_work import session_scope


class RunPlanCaseJobRepository(RunPlanCasePreparationRepository):
    @classmethod
    def _original(cls, session, command, project_id=None):
        if (command is None or command.tool_id != CASE_EXECUTE_TOOL or type(command.input_payload) is not dict
                or (project_id is not None and command.input_payload.get("project_id") != project_id)):
            raise RunPlanCaseExecutionInvalid("case lifecycle requires an original command in this project")
        preparation = PreparationJournal.verify(session, command)
        if preparation is None:
            raise RunPlanCaseExecutionInvalid("legacy case commands cannot be promoted to recoverable public jobs")
        cancellation = CancellationJournal.verify(session, command)
        if command.status == "cancelled" and cancellation is None:
            raise RunPlanCaseExecutionInvalid("case job cancellation lost its durable original control")
        selection = RunPlanCaseExecutionSelection.model_validate(PreparationJournal.selection(command))
        work = session.get(Work, PreparationJournal._work_id(selection.model_dump(mode="json")))
        scope = restore_case_scope(work.scope) if work is not None else None
        if scope is not None:
            Cases._work(session, scope, tuple(work.roster))
        if command.status == "completed" and scope is None:
            raise RunPlanCaseExecutionInvalid("completed case job lost its original complete work")
        return {"selection": selection, "invocation_id": command.id, "status": command.status,
            "command_digest": preparation["command_digest"], "actor_id": preparation["actor_id"], "scope": scope}

    def command(self, target):
        with session_scope() as session:
            return self._original(session, session.get(ToolInvocationRecord, target.invocation_id), target.project_id)

    def execution(self, invocation_id, *, require_actor=True):
        with session_scope() as session:
            command = self._original(session, session.get(ToolInvocationRecord, invocation_id))
            if require_actor:
                Cases._actor(session, command["selection"].project_id, command["actor_id"])
            actor = session.get(UserIdentityRecord, command["actor_id"])
            profile = UserProfile(id=actor.user_id, name=actor.display_name, email=actor.email, role=actor.role) if actor is not None else None
            if require_actor and profile is None:
                raise PermissionError("case lifecycle lost its original current actor")
            return command, profile

    def require_running(self, selection, invocation_id, command_digest, actor_id):
        with session_scope() as session:
            row = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
                .execution_options(populate_existing=True))
            command = self._original(session, row, selection.project_id)
            digest = verify_case_command_selection(PreparationJournal.snapshot(row), selection.model_dump(mode="json"),
                actor_id=actor_id, invocation_id=invocation_id, now=session.scalar(select(func.clock_timestamp())))
            if command["selection"] != selection or digest != command_digest:
                raise RunPlanCaseExecutionInvalid("case workflow cannot replace its independently confirmed command")
            Cases._actor(session, selection.project_id, actor_id)

    @staticmethod
    def _facts(session, scope):
        work = session.get(Work, scope.work_id)
        Cases._work(session, scope, tuple(work.roster))
        claims = [Cases._payload(row, CASE_CLAIM_SCHEMA) for row in session.scalars(select(Claim)
            .where(Claim.work_id == scope.work_id).order_by(Claim.ordinal)).all()]
        outcomes = [Cases._payload(row, CASE_OUTCOME_SCHEMA) for row in session.scalars(select(Outcome)
            .join(Claim, Outcome.claim_id == Claim.claim_id).where(Claim.work_id == scope.work_id).order_by(Claim.ordinal)).all()]
        return execution_state(scope, tuple(work.roster), claims, outcomes, cancelled=Cases._cancelled(session, scope)), outcomes

    @staticmethod
    def _event(session, command, *, actor_id=None, control_id=None):
        now, project_id = session.scalar(select(func.clock_timestamp())).isoformat(), command.input_payload["project_id"]
        session.add(AuditEventRecord(id=str(uuid4()), occurred_at=now, actor=actor_id or command.input_payload["confirmed_actor_id"],
            actor_kind="user", action="tool.invocation.updated", entity_type="tool_invocation", entity_id=command.id,
            status=command.status, summary="Original case lifecycle; not verified coverage or target rollback.",
            conversation_id=command.conversation_id, agent_goal_id=command.input_payload.get("agent_goal_id"),
            tool_invocation_id=command.id, object_refs=[], evidence_refs=[], event_metadata={"control_id": control_id} if control_id else {}))
        EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="tool.invocation.updated", occurred_at=now,
            correlation_id=project_id, entity_type="tool_invocation", entity_id=command.id, entity_version=command.revision,
            mutation_kind="replace", conversation_id=command.conversation_id, agent_goal_id=command.input_payload.get("agent_goal_id"),
            patch={"project_id": project_id, "tool_id": command.tool_id, "status": command.status},
            query_keys=[["run-plan-case-execution", project_id, command.id], ["tool-invocation", command.id]], snapshot_hint=True), session=session)

    def finish(self, invocation_id, command_digest, status, *, history=None, require_access=None):
        if status not in {"completed", "failed"}:
            raise RunPlanCaseExecutionInvalid("case finalization cannot invent cancellation or reopen an original job")
        with session_scope() as session:
            first = self._original(session, session.get(ToolInvocationRecord, invocation_id))
            TestDesignScopeRepository._lock(session, first["selection"].project_id)
            row = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
                .with_for_update().execution_options(populate_existing=True))
            command = self._original(session, row)
            if command["command_digest"] != command_digest:
                raise RunPlanCaseExecutionInvalid("case finalization lost its original confirmed command")
            if command["status"] != "running":
                return command["status"]
            scope = command["scope"]
            if status == "completed":
                if scope is None or type(history) is not dict or not callable(require_access):
                    raise RunPlanCaseExecutionInvalid("case completion needs durable original observations and current access")
                state, outcomes = self._facts(session, scope)
                observed = history.get("observations")
                if (history.get("historical_not_live") is not True or history.get("state") != state or state["state"] != "observed"
                        or type(observed) is not list or len(observed) != len(outcomes)
                        or any(type(value) is not dict or value.get("case_id") != outcome["case_id"]
                            or value.get("observation_digest") != outcome["observation_digest"] or value.get("status") != outcome["status"]
                            for value, outcome in zip(observed, outcomes))):
                    raise RunPlanCaseExecutionInvalid("unknown, incomplete or unverified case output cannot become completion")
                require_access()
            else:
                lease = session.get(Lease, scope.work_id) if scope is not None else None
                if lease is not None and lease.expires_at > session.scalar(select(func.clock_timestamp())):
                    raise RunPlanCaseWorkBusy("case failure must wait until the original worker is fenced")
            row.status = status
            row.summary = ("All original case observations archived; no formal business coverage or release evidence."
                if status == "completed" else "Original case execution ended; partial output and unknown effects are retained, never resent.")
            row.revision += 1
            row.result_payload = ToolResult(invocation_id=row.id, status=status, summary=row.summary).model_dump()
            self._event(session, row)
            if require_access is not None:
                require_access()
            return status

    def cancel(self, target, *, control_id, actor_id, require_current):
        require_current()
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, target.project_id)
            row = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == target.invocation_id)
                .with_for_update().execution_options(populate_existing=True))
            command = self._original(session, row, target.project_id)
            control = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == control_id)
                .with_for_update().execution_options(populate_existing=True))
            request = {key: item for key, item in query_payload(control.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}} if control is not None else None
            if request != target.model_dump(mode="json"):
                raise RunPlanCaseExecutionInvalid("case cancellation cannot control another command or scope")
            digest = verify_case_job_control(PreparationJournal.snapshot(control), request, actor_id=actor_id,
                now=session.scalar(select(func.clock_timestamp())))
            TestDesignResultRepository._project_scope(session, control, target.project_id)
            Cases._actor(session, target.project_id, actor_id)
            require_current()
            if command["status"] != "running":
                return command["status"]
            preparation = PreparationJournal.verify(session, row)
            value = {"schema": CASE_JOB_CANCELLATION_SCHEMA, **target.model_dump(mode="json"), "control_id": control_id,
                "actor_id": actor_id, "command_digest": command["command_digest"], "preparation_digest": acceptance_digest(preparation),
                "control_digest": digest, "recorded_at": session.scalar(select(func.clock_timestamp())).isoformat(), "status": "cancelled"}
            verify_case_job_cancellation(preparation, PreparationJournal.snapshot(control), value)
            session.add(PreparationJournal._row(Cancellation, value))
            row.status, row.summary = "cancelled", "Original case command cancelled; no target rollback, cleanup or unknown-effect retry."
            row.revision += 1
            row.result_payload = ToolResult(invocation_id=row.id, status="cancelled", summary=row.summary).model_dump()
            self._event(session, row, actor_id=actor_id, control_id=control_id)
            require_current()
            return "cancelled"

    def cancellation_delivered(self, invocation_id):
        with session_scope() as session:
            command = session.get(ToolInvocationRecord, invocation_id)
            original = self._original(session, command)
            TestDesignScopeRepository._lock(session, original["selection"].project_id)
            command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
                .with_for_update().execution_options(populate_existing=True))
            original = self._original(session, command)
            value = CancellationJournal.verify(session, command)
            if value is None:
                raise RunPlanCaseExecutionInvalid("case cancellation delivery cannot manufacture an original request")
            if session.get(Delivery, invocation_id) is not None:
                return
            receipt = {"schema": CASE_JOB_DELIVERY_SCHEMA, "invocation_id": invocation_id,
                "project_id": original["selection"].project_id, "cancellation_digest": acceptance_digest(value),
                "recorded_at": session.scalar(select(func.clock_timestamp())).isoformat()}
            session.add(PreparationJournal._row(Delivery, receipt))

    def pending_cancellations(self, *, after_id=None):
        with session_scope() as session:
            query = select(Cancellation.invocation_id).outerjoin(Delivery, Cancellation.invocation_id == Delivery.invocation_id)
            query = query.where(Delivery.invocation_id.is_(None))
            if after_id is not None:
                query = query.where(Cancellation.invocation_id > after_id)
            return tuple(session.scalars(query.order_by(Cancellation.invocation_id).limit(100)).all())
