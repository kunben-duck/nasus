"""ToolInvocation is lifecycle authority; effects remain in the original journal."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, or_, select, union_all

from ...application.platform.account_models import UserProfile
from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload, ToolResult
from ...application.quality_loop.http_fixture_commands import HttpFixtureCommandAuthority
from ...application.quality_loop.http_fixture_execution import HttpFixtureExecutionSelection
from ...application.quality_loop.http_fixture_jobs import HttpFixtureJobTarget
from ...application.quality_loop.http_fixture_work import HttpFixtureWorkBusy
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.http_fixture_command import FIXTURE_COMMAND_TOOL, FIXTURE_CANCEL_TOOL, FALSE_AUTHORITIES
from ...domain.quality_loop.http_fixture_preparation import PREPARATION_MARKER, PREPARATION_SCHEMA
from ...domain.quality_loop.http_fixtures import HttpFixtureInvalid, fixture_bindings, validate_http_fixture_manifest
from ..runner.http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from .db_models import AuditEventRecord, ToolInvocationRecord, UserIdentityRecord
from .event_outbox_repository import EventOutboxRepository
from .http_fixture_command_models import HttpFixtureCommandRecord as Intent, HttpFixtureDispatchCommandRecord as Binding
from .http_fixture_command_repository import HttpFixtureCommandRepository, _value, verify_dispatch_command
from .http_fixture_history_repository import HttpFixtureHistoryRepository
from .http_fixture_job_models import HttpFixtureCancellationRecord as Cancellation, HttpFixtureCancellationDeliveryRecord as Delivery
from .http_fixture_preparation_models import HttpFixturePreparationRecord as Preparation
from .http_fixture_preparation_cancel_models import HttpFixturePreparationCancellationRecord as PreparationCancellation, HttpFixturePreparationCancellationDeliveryRecord as PreparationDelivery
from .http_fixture_preparation_repository import HttpFixturePreparationJournal
from .http_fixture_journal_models import HttpFixtureDispatchRecord as Dispatch, HttpFixtureResultRecord as Result
from .http_fixture_work_models import HttpFixtureWorkLeaseRecord as Lease
from .http_fixture_work_repository import PostgresHttpFixtureWorkRepository
from .test_design_result_repository import TestDesignResultRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .unit_of_work import session_scope


CANCELLATION_SCHEMA = "nasus.http-fixture-cancellation.v1"
DELIVERY_SCHEMA = "nasus.http-fixture-cancellation-delivery.v1"
PREPARATION_CANCELLATION_SCHEMA = "nasus.http-fixture-preparation-cancellation.v1"
PREPARATION_DELIVERY_SCHEMA = "nasus.http-fixture-preparation-cancel-delivery.v1"


class HttpFixtureJobRepository(HttpFixtureCommandRepository, HttpFixtureHistoryRepository):
    @staticmethod
    def _selection(command):
        if (command is None or command.tool_id != FIXTURE_COMMAND_TOOL
                or type(command.input_payload) is not dict or command.input_payload.get("confirmed_by_user") is not True):
            raise HttpFixtureInvalid("fixture job requires an original independently confirmed execution command")
        return HttpFixtureExecutionSelection.model_validate({key: value for key, value in query_payload(command.input_payload).items()
            if key not in {"confirmed_by_user", "confirmed_at"}})

    @staticmethod
    def _authority(command):
        return HttpFixtureCommandAuthority(invocation_id=command.id,
            request_digest=acceptance_digest({"tool_id": command.tool_id, "input_payload": command.input_payload}))

    @classmethod
    def _original(cls, session, command):
        if command is None or command.tool_id != FIXTURE_COMMAND_TOOL or type(command.input_payload) is not dict:
            raise HttpFixtureInvalid("fixture lifecycle lost its original execution command")
        row = session.get(Intent, command.id)
        intent = cls._verify(session, row) if row is not None else None
        preparation = HttpFixturePreparationJournal.verify(session, command, intent=intent)
        if intent is not None and intent["request_digest"] != cls._authority(command).request_digest:
            raise HttpFixtureInvalid("fixture lifecycle original command digest changed")
        return preparation, intent

    def delivery(self, invocation_id):
        with session_scope() as session:
            command = session.get(ToolInvocationRecord, invocation_id)
            preparation, intent = self._original(session, command)
            if preparation is None and intent is None:
                raise HttpFixtureInvalid("legacy unbound commands cannot be promoted to recoverable preparation")
            return {"status": command.status, "bound": intent is not None, "authority": self._authority(command)}

    def failure_command(self, invocation_id):
        with session_scope() as session:
            command = session.get(ToolInvocationRecord, invocation_id)
            preparation, intent = self._original(session, command)
            authority = self._authority(command)
            if preparation is None or intent is not None:
                selection = self._selection(command)
                self._canonical(session, authority, selection, command.input_payload.get("confirmed_actor_id"), historical=True)
            return command.status, authority

    def command(self, invocation_id):
        with session_scope() as session:
            command = session.get(ToolInvocationRecord, invocation_id)
            self._original(session, command)
            selection, authority = self._selection(command), self._authority(command)
            return selection, command.status, authority

    def execution(self, invocation_id):
        with session_scope() as session:
            command = session.get(ToolInvocationRecord, invocation_id)
            self._original(session, command)
            selection, authority = self._selection(command), self._authority(command)
            actor_id = command.input_payload.get("confirmed_actor_id")
            self._canonical(session, authority, selection, actor_id)
            PostgresHttpFixtureWorkRepository._actor_current(session, selection.project_id, actor_id)
            actor = session.get(UserIdentityRecord, actor_id)
            return selection, UserProfile(id=actor.user_id, name=actor.display_name, email=actor.email, role=actor.role), authority

    def require_running(self, selection, authority, actor_id):
        with session_scope() as session:
            # Callbacks can run while the journal owns the original command lock.
            # Validate a read snapshot, never lock it on a second connection.
            command, confirmed = self._canonical(session, authority, selection, actor_id, historical=True)
            self._original(session, command)
            now = session.scalar(select(func.clock_timestamp()))
            if command.status != "running" or not 0 <= (now - confirmed).total_seconds() <= 900:
                raise HttpFixtureInvalid("fixture job is no longer running with fresh original confirmation")
            PostgresHttpFixtureWorkRepository._actor_current(session, selection.project_id, actor_id)
            row = session.get(Intent, authority.invocation_id)
            if row is not None and self._verify(session, row)["request_digest"] != authority.request_digest:
                raise HttpFixtureInvalid("fixture job lost its original intent")

    @classmethod
    def _state(cls, session, inputs, authority, history):
        from .http_fixture_journal_repository import PostgresHttpFixtureDispatchJournal as Journal

        command, _ = cls._canonical(session, authority, inputs.selection, inputs.consent.actor_id, historical=True)
        value = cls._verify(session, session.get(Intent, authority.invocation_id))
        cls._matches(inputs, value)
        manifest = validate_http_fixture_manifest(inputs.manifest)
        if acceptance_digest(manifest) != inputs.scope.data_manifest_hash:
            raise HttpFixtureInvalid("fixture job phase inventory is not its original manifest")
        expected = ("setup",) if inputs.selection.operation == "setup" else (
            "setup", *("cleanup:" + binding for binding in fixture_bindings(manifest)))
        if (type(history) is not tuple or tuple(item[0] for item in history) != expected
                or len({item[0] for item in history}) != len(expected)):
            raise HttpFixtureInvalid("fixture job needs its complete original archive history")
        phases = []
        for phase, observed in history:
            if inputs.selection.operation == "cleanup" and phase == "setup":
                continue
            claim_id = Journal._identity(inputs.scope, phase)
            dispatch = Journal._value(session.get(Dispatch, claim_id))
            result = Journal._value(session.get(Result, claim_id))
            if dispatch is None:
                if result is not None or observed is not None or session.get(Binding, claim_id) is not None:
                    raise HttpFixtureInvalid("fixture job cannot fabricate an unrecorded phase")
                phases.append({"phase": phase, "claim_id": claim_id, "state": "not_dispatched"})
                continue
            pin = verify_dispatch_command(session, dispatch)
            if (pin is None or pin["invocation_id"] != authority.invocation_id or observed is None
                    or dispatch["scope_digest"] != inputs.scope.digest
                    or acceptance_digest(Journal._command_value(observed.command)) != acceptance_digest(dispatch["command"])):
                raise HttpFixtureInvalid("fixture job cannot adopt a private or another command's phase")
            item = {"phase": phase, "claim_id": claim_id, "dispatch_digest": acceptance_digest(dispatch)}
            if result is None:
                if observed.execution is not None:
                    raise HttpFixtureInvalid("fixture job cannot invent uncommitted output")
                item["state"] = "outcome_unknown"
            else:
                if observed.execution is None:
                    raise HttpFixtureInvalid("fixture job lost the original archived output")
                receipt = OwnedHttpFixtureObservationVerifier().verify(observed.command, observed.execution,
                    environment_id=inputs.scope.environment_id, inventory_hash=inputs.scope.inventory_hash)
                if (result["schema"] != "nasus.http-fixture-result.v1"
                        or result["dispatch_digest"] != acceptance_digest(dispatch)
                        or result["actor_id"] != dispatch["actor_id"]
                        or result["receipt_digest"] != acceptance_digest(receipt)
                        or result["status"] != observed.execution.result.status):
                    raise HttpFixtureInvalid("fixture job observation is not its original journal result")
                item.update(state="observed", result_status=result["status"], result_digest=acceptance_digest(result))
            phases.append(item)
        cancellation = cls._cancellation(session, authority.invocation_id)
        return {"schema": "nasus.http-fixture-job.v1", "project_id": inputs.selection.project_id,
            "invocation_id": authority.invocation_id, "request_digest": authority.request_digest,
            "selection": inputs.selection.model_dump(mode="json"), "status": command.status,
            "intent_digest": acceptance_digest(value), "phases": phases,
            "cancellation_requested": cancellation is not None,
            "cancellation_delivered": session.get(Delivery, authority.invocation_id) is not None,
            **{key: False for key in FALSE_AUTHORITIES}}

    def state(self, inputs, authority, history):
        with session_scope() as session:
            return self._state(session, inputs, authority, history)

    def preparation_state(self, inputs, authority):
        with session_scope() as session:
            command, _ = self._canonical(session, authority, inputs.selection, inputs.consent.actor_id, historical=True)
            preparation, intent = self._original(session, command)
            if intent is not None:
                self._matches(inputs, intent)
                return None
            if preparation is None:
                raise HttpFixtureInvalid("legacy unbound commands have no verified preparation observation")
            if command.status == "completed":
                raise HttpFixtureInvalid("unbound preparation cannot be a completed fixture execution")
            cancellation = self._cancellation(session, authority.invocation_id)
            if command.status == "cancelled" and cancellation is None:
                raise HttpFixtureInvalid("cancelled preparation lost its original cancellation history")
            return {"schema": "nasus.http-fixture-job.v2", "project_id": inputs.selection.project_id,
                "invocation_id": authority.invocation_id, "request_digest": authority.request_digest,
                "selection": inputs.selection.model_dump(mode="json"), "status": command.status,
                "preparation_digest": acceptance_digest(preparation), "intent_digest": None,
                "phase": {"running": "preparing", "failed": "preparation_failed", "cancelled": "preparation_cancelled"}[command.status],
                "phases": [], "target_observation_verified": False,
                "cancellation_requested": cancellation is not None,
                "cancellation_delivered": session.get(PreparationDelivery, authority.invocation_id) is not None,
                **{key: False for key in FALSE_AUTHORITIES}}

    def finish(self, authority, status, *, inputs=None, history=None, require_current=None):
        if status not in {"completed", "failed"}:
            raise HttpFixtureInvalid("fixture worker cannot manufacture a cancellation or reopen a command")
        with session_scope() as session:
            original = session.get(ToolInvocationRecord, authority.invocation_id)
            preparation, value = self._original(session, original)
            if self._authority(original) != authority:
                raise HttpFixtureInvalid("fixture termination lost its original command")
            unbound_failure = status == "failed" and preparation is not None and value is None
            selection = None if unbound_failure else self._selection(original)
            project_id = preparation["project_id"] if unbound_failure else selection.project_id
            TestDesignScopeRepository._lock(session, project_id)
            command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == authority.invocation_id)
                .with_for_update().execution_options(populate_existing=True))
            preparation, value = self._original(session, command)
            if self._authority(command) != authority:
                raise HttpFixtureInvalid("fixture termination original input changed while acquiring its lock")
            # Binding may have won the project lock since the read above. Never
            # bypass its original selection, parent verification or live lease.
            if not (unbound_failure and preparation is not None and value is None):
                selection = self._selection(command)
                self._canonical(session, authority, selection, command.input_payload.get("confirmed_actor_id"), historical=True)
            if command.status != "running":
                return command.status
            if status == "completed":
                if value is None or inputs is None or history is None or not callable(require_current):
                    raise HttpFixtureInvalid("fixture completion needs complete durable original observations")
                state = self._state(session, inputs, authority, history)
                if not state["phases"] or any(item["state"] != "observed" for item in state["phases"]):
                    raise HttpFixtureInvalid("unknown or unexecuted fixture phases cannot become completion")
                require_current()
            else:
                work = session.get(Lease, value["work_id"]) if value is not None else None
                if work is not None and work.expires_at > session.scalar(select(func.clock_timestamp())):
                    raise HttpFixtureWorkBusy("fixture termination must wait until the original worker is fenced")
            command.status = status
            command.summary = ("Original fixture operation archived; no business coverage or baseline restoration verified."
                if status == "completed" else "Fixture operation ended; any unknown effect is retained and never automatically resent.")
            command.revision += 1
            command.result_payload = ToolResult(invocation_id=command.id, status=status, summary=command.summary).model_dump()
            self._lifecycle_event(session, command, "tool.invocation.updated")
            if require_current is not None:
                require_current()
            return status

    @classmethod
    def _control(cls, session, target, control_id, actor_id, *, historical=False):
        try:
            if (type(actor_id) is not str or not actor_id.strip() or len(actor_id) > 128
                    or any(ord(char) < 32 for char in actor_id)):
                raise HttpFixtureInvalid("fixture cancellation requires its exact independent confirming actor")
            query = select(ToolInvocationRecord).where(ToolInvocationRecord.id == control_id)
            control = session.scalar(query if historical else query.with_for_update().execution_options(populate_existing=True))
            if (control is None or control.tool_id != FIXTURE_CANCEL_TOOL
                    or control.status not in ({"running", "completed", "failed", "cancelled"} if historical else {"running"})
                    or control.input_payload.get("confirmed_by_user") is not True
                    or control.input_payload.get("confirmed_actor_id") != actor_id
                    or HttpFixtureJobTarget.model_validate({key: value for key, value in query_payload(control.input_payload).items()
                        if key not in {"confirmed_by_user", "confirmed_at"}}) != target):
                raise HttpFixtureInvalid("fixture cancellation needs its independently confirmed exact control command")
            TestDesignResultRepository._project_scope(session, control, target.project_id)
            confirmed = datetime.fromisoformat(control.input_payload["confirmed_at"])
            if confirmed.tzinfo is None or (not historical and not 0 <= (
                    session.scalar(select(func.clock_timestamp())) - confirmed).total_seconds() <= 900):
                raise HttpFixtureInvalid("fixture cancellation confirmation is not fresh by PostgreSQL time")
            return control
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
            if isinstance(exc, HttpFixtureInvalid):
                raise
            raise HttpFixtureInvalid("fixture original cancellation control cannot be verified") from exc

    @classmethod
    def _cancellation(cls, session, invocation_id):
        try:
            return cls._verify_cancellation(session, invocation_id)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
            if isinstance(exc, HttpFixtureInvalid):
                raise
            raise HttpFixtureInvalid("fixture cancellation history cannot be verified") from exc

    @classmethod
    def _verify_cancellation(cls, session, invocation_id):
        row = session.get(Cancellation, invocation_id)
        delivery = session.get(Delivery, invocation_id)
        unbound = session.get(PreparationCancellation, invocation_id)
        unbound_delivery = session.get(PreparationDelivery, invocation_id)
        if row is None and unbound is None:
            if delivery is not None or unbound_delivery is not None:
                raise HttpFixtureInvalid("fixture cancellation delivery lost its original request")
            return None
        if (row is not None and (unbound is not None or unbound_delivery is not None)) or (unbound is not None and delivery is not None):
            raise HttpFixtureInvalid("fixture cancellation cannot adopt another lifecycle branch")
        command = session.get(ToolInvocationRecord, invocation_id)
        if command is None or command.tool_id != FIXTURE_COMMAND_TOOL or type(command.input_payload) is not dict:
            raise HttpFixtureInvalid("fixture cancellation lost its original execution command")
        if unbound is not None:
            value = _value(unbound, PREPARATION_CANCELLATION_SCHEMA)
            if session.get(Intent, invocation_id) is not None:
                raise HttpFixtureInvalid("cancelled original preparation cannot manufacture an execution intent")
            intent = HttpFixturePreparationJournal.verify(session, command)
            if intent is None or value["preparation_digest"] != acceptance_digest(intent):
                raise HttpFixtureInvalid("fixture preparation cancellation lost its original claim")
            delivery, delivery_schema = unbound_delivery, PREPARATION_DELIVERY_SCHEMA
        else:
            value = _value(row, CANCELLATION_SCHEMA)
            intent = cls._verify(session, session.get(Intent, invocation_id))
            delivery_schema = DELIVERY_SCHEMA
        control = cls._control(session, HttpFixtureJobTarget(project_id=value["project_id"], invocation_id=invocation_id),
            value["control_id"], value["actor_id"], historical=True)
        if (command.status != "cancelled" or value["project_id"] != intent["project_id"]
                or value["request_digest"] != intent["request_digest"]
                or value["control_digest"] != cls._authority(control).request_digest
                or not 0 <= (datetime.fromisoformat(value["recorded_at"]) - datetime.fromisoformat(
                    control.input_payload["confirmed_at"])).total_seconds() <= 900):
            raise HttpFixtureInvalid("fixture cancellation lost its unchanged original commands")
        if delivery is not None:
            delivered = _value(delivery, delivery_schema)
            if (delivered["project_id"] != value["project_id"] or delivered["cancellation_digest"] != acceptance_digest(value)
                    or datetime.fromisoformat(delivered["recorded_at"]) < datetime.fromisoformat(value["recorded_at"])):
                raise HttpFixtureInvalid("fixture cancellation delivery cannot adopt another request")
        return value

    def cancel(self, target, *, control_id, actor_id, require_current):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, target.project_id)
            command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == target.invocation_id)
                .with_for_update().execution_options(populate_existing=True))
            preparation, intent = self._original(session, command)
            value = intent if intent is not None else preparation
            if value is None:
                raise HttpFixtureInvalid("fixture cancellation cannot promote an unverified legacy preparation")
            if value["project_id"] != target.project_id:
                raise PermissionError("fixture cancellation project differs")
            prior = self._cancellation(session, target.invocation_id)
            control = self._control(session, target, control_id, actor_id,
                historical=prior is not None and prior["control_id"] == control_id)
            PostgresHttpFixtureWorkRepository._actor_current(session, target.project_id, actor_id)
            require_current()
            if command.status != "running":
                return command.status
            command.status, command.summary = "cancelled", "Fixture cancellation recorded; committed observations remain, unknown effects are not resent."
            command.revision += 1
            command.result_payload = ToolResult(invocation_id=command.id, status="cancelled", summary=command.summary).model_dump()
            payload = {"schema": CANCELLATION_SCHEMA if intent is not None else PREPARATION_CANCELLATION_SCHEMA,
                "project_id": target.project_id, "invocation_id": target.invocation_id,
                "control_id": control_id, "control_digest": self._authority(control).request_digest,
                "request_digest": value["request_digest"], "actor_id": actor_id,
                "recorded_at": session.scalar(select(func.clock_timestamp())).isoformat(), **{key: False for key in FALSE_AUTHORITIES}}
            if intent is None:
                payload["preparation_digest"] = acceptance_digest(preparation)
            session.add(self._row(Cancellation if intent is not None else PreparationCancellation, payload))
            session.flush()
            self._cancellation(session, target.invocation_id)
            self._lifecycle_event(session, command, "tool.invocation.updated", actor_id=actor_id, control_id=control_id)
            self._lifecycle_event(session, command, "quality.http_fixture.cancel_requested", actor_id=actor_id, control_id=control_id,
                occurred_at=payload["recorded_at"])
            require_current()
            return "cancelled"

    def cancellation_delivered(self, target):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, target.project_id)
            value = self._cancellation(session, target.invocation_id)
            if value is None or value["project_id"] != target.project_id:
                raise HttpFixtureInvalid("fixture cancellation delivery requires its exact original request")
            model, schema = self._delivery_branch(value)
            if session.get(model, target.invocation_id) is not None:
                return
            payload = {"schema": schema, "project_id": target.project_id, "invocation_id": target.invocation_id,
                "cancellation_digest": acceptance_digest(value), "recorded_at": session.scalar(select(func.clock_timestamp())).isoformat(),
                **{key: False for key in FALSE_AUTHORITIES}}
            session.add(self._row(model, payload))
            session.flush()
            self._cancellation(session, target.invocation_id)
            self._lifecycle_event(session, session.get(ToolInvocationRecord, target.invocation_id), "quality.http_fixture.cancel_delivered",
                actor_id=value["actor_id"], control_id=value["control_id"], occurred_at=payload["recorded_at"], actor_kind="system")

    def pending(self, *, after_id=None, limit=100):
        with session_scope() as session:
            query = select(ToolInvocationRecord).outerjoin(Intent, ToolInvocationRecord.id == Intent.invocation_id).outerjoin(
                Preparation, ToolInvocationRecord.id == Preparation.invocation_id).where(
                ToolInvocationRecord.tool_id == FIXTURE_COMMAND_TOOL, ToolInvocationRecord.status == "running",
                or_(Intent.invocation_id.is_not(None), Preparation.invocation_id.is_not(None),
                    ToolInvocationRecord.input_payload[PREPARATION_MARKER].as_string() == PREPARATION_SCHEMA))
            if after_id:
                query = query.where(ToolInvocationRecord.id > after_id)
            return [(row.id, row.input_payload.get("project_id")) for row in session.scalars(
                query.order_by(ToolInvocationRecord.id).limit(min(max(limit, 1), 100)))]

    def pending_cancellations(self, *, after_id=None, limit=100):
        with session_scope() as session:
            pending = union_all(
                select(Cancellation.invocation_id, Cancellation.project_id).outerjoin(Delivery,
                    Delivery.invocation_id == Cancellation.invocation_id).where(Delivery.invocation_id.is_(None)),
                select(PreparationCancellation.invocation_id, PreparationCancellation.project_id).outerjoin(PreparationDelivery,
                    PreparationDelivery.invocation_id == PreparationCancellation.invocation_id).where(PreparationDelivery.invocation_id.is_(None)),
            ).subquery()
            query = select(pending.c.invocation_id, pending.c.project_id)
            if after_id:
                query = query.where(pending.c.invocation_id > after_id)
            return [(row.invocation_id, row.project_id) for row in session.execute(
                query.order_by(pending.c.invocation_id).limit(min(max(limit, 1), 100)))]

    @staticmethod
    def _delivery_branch(value):
        return (PreparationDelivery, PREPARATION_DELIVERY_SCHEMA) if value["schema"] == PREPARATION_CANCELLATION_SCHEMA else (Delivery, DELIVERY_SCHEMA)

    @classmethod
    def verify_event(cls, session, event):
        if event.event_type not in {"quality.http_fixture.cancel_requested", "quality.http_fixture.cancel_delivered"}:
            return
        value = cls._cancellation(session, event.entity_id)
        if value is None:
            raise HttpFixtureInvalid("fixture cancellation event lost its original request")
        fact = value
        if event.event_type == "quality.http_fixture.cancel_delivered":
            model, schema = cls._delivery_branch(value)
            fact = _value(session.get(model, event.entity_id), schema)
        command = session.get(ToolInvocationRecord, event.entity_id)
        if (event.entity_type != "tool_invocation" or event.mutation_kind != "append"
                or event.occurred_at != fact["recorded_at"] or event.correlation_id != value["project_id"]
                or event.conversation_id != command.conversation_id
                or event.agent_goal_id != command.input_payload.get("agent_goal_id")
                or event.patch != {"project_id": value["project_id"], "tool_id": FIXTURE_COMMAND_TOOL, "status": "cancelled"}
                or event.query_keys != [["http-fixture-execution", value["project_id"], command.id], ["tool-invocation", command.id]]
                or event.snapshot_hint is not True or event.payload != {}
                or any(getattr(event, key) is not None for key in
                    ("tool_invocation_id", "agent_step_id", "swarm_run_id", "assignment_id", "task_id", "run_id"))):
            raise HttpFixtureInvalid("fixture cancellation event is not its exact immutable metadata")

    @staticmethod
    def _lifecycle_event(session, command, kind, *, actor_id=None, control_id=None, occurred_at=None, actor_kind="user"):
        now = occurred_at or session.scalar(select(func.clock_timestamp())).isoformat()
        project_id = command.input_payload["project_id"]
        metadata = {"control_id": control_id} if control_id is not None else {}
        session.add(AuditEventRecord(id=str(uuid4()), occurred_at=now, actor=actor_id or command.input_payload["confirmed_actor_id"],
            actor_kind=actor_kind, action=kind, entity_type="tool_invocation", entity_id=command.id, status=command.status,
            summary="Original fixture lifecycle; no business coverage or baseline restoration.", conversation_id=command.conversation_id,
            agent_goal_id=command.input_payload.get("agent_goal_id"), tool_invocation_id=command.id, object_refs=[], evidence_refs=[], event_metadata=metadata))
        EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=kind, occurred_at=now,
            correlation_id=project_id, entity_type="tool_invocation", entity_id=command.id, entity_version=command.revision,
            mutation_kind="replace" if kind == "tool.invocation.updated" else "append", conversation_id=command.conversation_id,
            agent_goal_id=command.input_payload.get("agent_goal_id"), patch={"project_id": project_id, "tool_id": command.tool_id,
                "status": command.status}, query_keys=[["http-fixture-execution", project_id, command.id], ["tool-invocation", command.id]],
            snapshot_hint=True), session=session)
