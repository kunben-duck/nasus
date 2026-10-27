"""Canonical command fences share the original journal transaction and locks."""
from dataclasses import asdict
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, or_, select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.quality_loop.http_fixture_commands import HttpFixtureCommandAuthority
from ...application.quality_loop.http_fixture_diagnostics import fixture_phase
from ...application.quality_loop.http_fixture_execution import HttpFixtureExecutionSelection
from ...application.quality_loop.http_fixture_work import fixture_work_identity
from ...application.quality_loop.http_fixtures import HttpFixtureScope
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.http_fixture_command import (
    FIXTURE_COMMAND_SCHEMA, FIXTURE_CANONICAL_DISPATCH_SCHEMA, FIXTURE_DISPATCH_COMMAND_SCHEMA,
    FALSE_AUTHORITIES, verify_fixture_command,
)
from ...domain.quality_loop.http_fixture_grant import NATIVE_GRANT_SCHEMA
from ...domain.quality_loop.http_fixtures import HttpFixtureInvalid
from .db_models import AuditEventRecord, ToolInvocationRecord
from .event_outbox_repository import EventOutboxRepository
from .http_fixture_command_models import HttpFixtureCommandRecord as Intent, HttpFixtureDispatchCommandRecord as Binding
from .http_fixture_preparation_repository import HttpFixturePreparationJournal
from .http_fixture_grant_models import HttpFixtureGrantRecord as Grant
from .http_fixture_grant_repository import HttpFixtureGrantRepository
from .http_fixture_work_repository import PostgresHttpFixtureWorkRepository, verify_dispatch_ownership
from .http_fixture_dispatch_consent_repository import verify_dispatch_consent
from .http_fixture_journal_models import HttpFixtureDispatchRecord as Dispatch
from .test_design_result_repository import TestDesignResultRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .unit_of_work import session_scope


def _value(row, schema, *, extra=()):
    if row is None:
        raise HttpFixtureInvalid("original fixture command provenance is missing")
    columns = {column.name for column in row.__table__.columns} - {"payload", "content_hash"}
    value = row.payload
    if (type(value) is not dict or set(value) != columns | {"schema", *FALSE_AUTHORITIES, *extra}
            or value.get("schema") != schema or acceptance_digest(value) != row.content_hash
            or any(value.get(key) != getattr(row, key) for key in columns)
            or any(value.get(key) is not False for key in FALSE_AUTHORITIES)):
        raise HttpFixtureInvalid("original fixture command columns, bytes or authority differ")
    return value


class HttpFixtureCommandRepository:
    @staticmethod
    def _canonical(session, authority, selection, actor_id, *, historical=False):
        query = select(ToolInvocationRecord).where(ToolInvocationRecord.id == authority.invocation_id)
        # A cancellation/terminal write must take this same command row lock.
        command = session.scalar((query if historical else query.with_for_update()).execution_options(populate_existing=True))
        if command is None:
            raise HttpFixtureInvalid("original fixture command is missing")
        try:
            request = HttpFixtureExecutionSelection.model_validate({key: value
                for key, value in query_payload(command.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}})
        except (ValueError, TypeError, AttributeError) as exc:
            raise HttpFixtureInvalid("original fixture command contains an unverified execution selection") from exc
        if request != selection:
            raise HttpFixtureInvalid("fixture command cannot change its original grant or operation")
        snapshot = {key: getattr(command, key) for key in ("id", "tool_id", "status", "input_payload")}
        confirmed = verify_fixture_command(snapshot, request.model_dump(mode="json"),
            invocation_id=authority.invocation_id, request_digest=authority.request_digest, actor_id=actor_id,
            historical=historical, now=None if historical else session.scalar(select(func.clock_timestamp())))
        TestDesignResultRepository._project_scope(session, command, selection.project_id)
        return command, confirmed

    @classmethod
    def _verify(cls, session, row):
        value = _value(row, FIXTURE_COMMAND_SCHEMA, extra=("selection", "scope", "parent", "native_environment"))
        try:
            selection = HttpFixtureExecutionSelection.model_validate(value["selection"])
            authority = HttpFixtureCommandAuthority(invocation_id=value["invocation_id"], request_digest=value["request_digest"])
            scope = HttpFixtureScope(**value["scope"])
            grant = session.get(Grant, selection.grant_id)
            original = HttpFixtureGrantRepository._verify(session, grant)
            grant_command = session.get(ToolInvocationRecord, grant.invocation_id)
            command, confirmed = cls._canonical(session, authority, selection, value["actor_id"], historical=True)
            HttpFixturePreparationJournal.verify(session, command, intent=value)
            parent = HttpFixtureGrantRepository._parents(session, HttpFixtureGrantRepository._request(
                grant_command))
            if (grant_command.status != "completed" or original["schema"] != NATIVE_GRANT_SCHEMA
                    or selection.project_id != value["project_id"]
                    or selection.grant_id != value["grant_id"] or selection.grant_digest != value["grant_digest"]
                    or selection.operation != value["operation"] or scope.project_id != value["project_id"]
                    or value["grant_digest"] != original["grant_digest"] or value["actor_id"] != original["actor_id"]
                    or scope.digest != value["scope_digest"] or asdict(scope) != original["scope"]
                    or value["operation"] != original["operation"]
                    or value["source_scope_digest"] != original["source_scope_digest"]
                    or value["work_id"] != fixture_work_identity(scope, value["operation"])
                    or value["native_environment"] != original["native_environment"]
                    or value["parent"] != {key: parent[key] for key in
                        ("project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest")}
                    or not datetime.fromisoformat(original["recorded_at"]) <= confirmed
                        <= datetime.fromisoformat(value["recorded_at"]) < datetime.fromisoformat(original["expires_at"])):
                raise HttpFixtureInvalid("fixture command lost its exact original native consent or parent")
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
            if isinstance(exc, HttpFixtureInvalid):
                raise
            raise HttpFixtureInvalid("original fixture command ancestry cannot be verified") from exc
        return value

    @staticmethod
    def _row(model, payload):
        columns = {column.name for column in model.__table__.columns} - {"payload", "content_hash"}
        return model(**{key: payload[key] for key in columns}, payload=payload, content_hash=acceptance_digest(payload))

    @classmethod
    def _matches(cls, inputs, value):
        if (inputs.selection.model_dump(mode="json") != value["selection"] or asdict(inputs.scope) != value["scope"]
                or inputs.parent.model_dump(mode="json") != value["parent"]
                or inputs.native_environment != value["native_environment"]
                or inputs.consent.actor_id != value["actor_id"]
                or inputs.consent.source_scope_digest != value["source_scope_digest"]):
            raise HttpFixtureInvalid("fixture worker cannot rebind its original command inputs")

    def bind(self, inputs, authority, *, require_current):
        authority = HttpFixtureCommandAuthority.model_validate(authority.model_dump(mode="json"))
        with fixture_phase("bind_current_authority"):
            require_current()
        with session_scope() as session:
            with fixture_phase("bind_canonical"):
                TestDesignScopeRepository._lock(session, inputs.selection.project_id)
                command, _ = self._canonical(session, authority, inputs.selection, inputs.consent.actor_id)
                PostgresHttpFixtureWorkRepository._actor_current(session, inputs.scope.project_id, inputs.consent.actor_id)
            with fixture_phase("bind_live_permission"):
                original = HttpFixtureGrantRepository().require_live_in_session(session, inputs.scope.project_id,
                    inputs.consent.grant_id, actor_id=inputs.consent.actor_id, scope=inputs.scope,
                    operation=inputs.selection.operation, source_scope_digest=inputs.consent.source_scope_digest)
                if original["schema"] != NATIVE_GRANT_SCHEMA or original["grant_digest"] != inputs.selection.grant_digest:
                    raise HttpFixtureInvalid("fixture command requires the exact original native consent")
            row = session.get(Intent, authority.invocation_id)
            if row is not None:
                with fixture_phase("bind_existing_intent"):
                    value = self._verify(session, row)
                    self._matches(inputs, value)
                with fixture_phase("bind_current_authority"):
                    require_current()
                return value
            with fixture_phase("bind_preparation"):
                HttpFixturePreparationJournal.verify(session, command)
            with fixture_phase("bind_prior_effects"):
                work_id = fixture_work_identity(inputs.scope, inputs.selection.operation)
                reused = session.scalar(select(Intent).where(or_(Intent.grant_id == inputs.selection.grant_id, Intent.work_id == work_id)))
                if reused is not None:
                    self._verify(session, reused)
                    raise HttpFixtureInvalid("original fixture consent or work already belongs to another canonical command")
                phase = Dispatch.phase == "setup" if inputs.selection.operation == "setup" else Dispatch.phase.like("cleanup:%")
                dispatched = session.scalar(select(Dispatch).where(Dispatch.project_id == inputs.scope.project_id,
                    Dispatch.attempt_id == inputs.scope.attempt_id, Dispatch.case_id == inputs.scope.case_id, phase).limit(1))
                if dispatched is not None:
                    raise HttpFixtureInvalid("new canonical command cannot adopt an already dispatched private or unknown operation")
            with fixture_phase("bind_current_authority"):
                require_current()
            value = {"schema": FIXTURE_COMMAND_SCHEMA, **authority.model_dump(mode="json"),
                **inputs.selection.model_dump(mode="json"), "actor_id": inputs.consent.actor_id,
                "scope_digest": inputs.scope.digest, "source_scope_digest": inputs.consent.source_scope_digest,
                "work_id": work_id,
                "recorded_at": session.scalar(select(func.clock_timestamp())).isoformat(),
                "selection": inputs.selection.model_dump(mode="json"), "scope": asdict(inputs.scope),
                "parent": inputs.parent.model_dump(mode="json"), "native_environment": inputs.native_environment,
                **{key: False for key in FALSE_AUTHORITIES}}
            with fixture_phase("bind_intent_persistence"):
                row = self._row(Intent, value)
                session.add(row)
                session.flush()
            with fixture_phase("bind_preparation_receipt"):
                HttpFixturePreparationJournal.bind(session, command, value)
            with fixture_phase("bind_intent_verification"):
                self._verify(session, row)
            with fixture_phase("bind_event_persistence"):
                self._event(session, value)
            with fixture_phase("bind_current_authority"):
                require_current()
            return value

    def _require_in_session(self, session, inputs, authority):
        self._canonical(session, authority, inputs.selection, inputs.consent.actor_id)
        value = self._verify(session, session.get(Intent, authority.invocation_id))
        self._matches(inputs, value)
        PostgresHttpFixtureWorkRepository._actor_current(session, inputs.scope.project_id, inputs.consent.actor_id)
        return value

    def require(self, inputs, authority):
        with session_scope() as session:
            # No lock on a second connection while the journal owns this row.
            value = self._verify(session, session.get(Intent, authority.invocation_id))
            self._matches(inputs, value)
            command = session.get(ToolInvocationRecord, authority.invocation_id)
            if command.status != "running" or value["request_digest"] != authority.request_digest:
                raise HttpFixtureInvalid("fixture command is no longer running with its original input")
            PostgresHttpFixtureWorkRepository._actor_current(session, inputs.scope.project_id, inputs.consent.actor_id)

    def fence(self, inputs, authority):
        return PostgresHttpFixtureCommandFence(self, inputs, authority)

    @staticmethod
    def _event(session, value):
        kind = "quality.http_fixture.command_bound"
        summary = "Original fixture command bound; no target request or business coverage recorded."
        command = session.get(ToolInvocationRecord, value["invocation_id"])
        session.add(AuditEventRecord(id=str(uuid4()), occurred_at=value["recorded_at"], actor=value["actor_id"],
            actor_kind="user", action=kind, entity_type="http_fixture_command", entity_id=value["invocation_id"],
            status="recorded", summary=summary, conversation_id=command.conversation_id,
            agent_goal_id=command.input_payload.get("agent_goal_id"), tool_invocation_id=value["invocation_id"],
            object_refs=["http_fixture_command:" + value["invocation_id"]], evidence_refs=[], event_metadata={}))
        EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=kind,
            occurred_at=value["recorded_at"], correlation_id=value["project_id"], entity_type="http_fixture_command",
            entity_id=value["invocation_id"], entity_version=0, mutation_kind="append",
            conversation_id=command.conversation_id, agent_goal_id=command.input_payload.get("agent_goal_id"),
            patch={key: value[key] for key in ("project_id", "invocation_id")},
            query_keys=[["http-fixture-command", value["project_id"], value["invocation_id"]]], snapshot_hint=True), session=session)

    @classmethod
    def verify_event(cls, session, event):
        if event.event_type != "quality.http_fixture.command_bound":
            return
        value = cls._verify(session, session.get(Intent, event.entity_id))
        command = session.get(ToolInvocationRecord, value["invocation_id"])
        if (event.entity_type != "http_fixture_command" or event.correlation_id != value["project_id"]
                or event.occurred_at != value["recorded_at"]
                # Outbox assigns its sequence before fact validation and verifies it on replay.
                or type(event.entity_version) is not int or event.entity_version < 0
                or event.conversation_id != command.conversation_id
                or event.agent_goal_id != command.input_payload.get("agent_goal_id")
                or event.mutation_kind != "append" or event.snapshot_hint is not True or event.payload != {}
                or event.patch != {key: value[key] for key in ("project_id", "invocation_id")}
                or event.query_keys != [["http-fixture-command", value["project_id"], value["invocation_id"]]]
                or any(getattr(event, key) is not None for key in
                    ("tool_invocation_id", "agent_step_id", "swarm_run_id", "assignment_id", "task_id", "run_id"))):
            raise HttpFixtureInvalid("fixture command event differs from its original immutable intent")


def _related_command(session, scope, phase):
    operation = "setup" if phase == "setup" else "cleanup"
    row = session.scalar(select(Intent).where(Intent.work_id == fixture_work_identity(scope, operation)))
    return HttpFixtureCommandRepository._verify(session, row) if row is not None else None


def require_private_fixture_work(session, scope, phase):
    """The same project lock serializes binding and private dispatch claims."""
    if _related_command(session, scope, phase) is not None:
        raise HttpFixtureInvalid("command-bound fixture work cannot fall back to private dispatch")


def verify_dispatch_command(session, dispatch):
    """Verify immutable ancestry after termination; never check live TTL or dispatch."""
    try:
        row = session.get(Binding, dispatch["claim_id"])
        if row is None:
            related = (_related_command(session, HttpFixtureScope(**dispatch["scope"]), dispatch["phase"])
                if type(dispatch.get("scope")) is dict else None)
            if dispatch.get("schema") == FIXTURE_CANONICAL_DISPATCH_SCHEMA or "canonical_command" in dispatch or related is not None:
                raise HttpFixtureInvalid("original fixture dispatch command is missing; never downgrade it")
            return None
        value = _value(row, FIXTURE_DISPATCH_COMMAND_SCHEMA)
        intent = HttpFixtureCommandRepository._verify(session, session.get(Intent, value["invocation_id"]))
        pin = {"invocation_id": value["invocation_id"], "intent_digest": value["intent_digest"], "request_digest": value["request_digest"]}
        operation = "setup" if dispatch["phase"] == "setup" else "cleanup"
        if (dispatch.get("schema") != FIXTURE_CANONICAL_DISPATCH_SCHEMA or dispatch.get("canonical_command") != pin
                or value["claim_id"] != dispatch["claim_id"] or value["project_id"] != dispatch["project_id"]
                or value["dispatch_digest"] != acceptance_digest(dispatch) or value["intent_digest"] != acceptance_digest(intent)
                or value["request_digest"] != intent["request_digest"] or dispatch["scope"] != intent["scope"]
                or dispatch["actor_id"] != intent["actor_id"] or intent["operation"] != operation
                or value["recorded_at"] != dispatch["recorded_at"]
                or datetime.fromisoformat(value["recorded_at"]) < datetime.fromisoformat(intent["recorded_at"])
                or dispatch.get("operation_consent") != {key: intent[key] for key in
                    ("grant_id", "grant_digest", "source_scope_digest")}
                or dispatch.get("work_ownership", {}).get("work_id") != intent["work_id"]
                or verify_dispatch_ownership(session, dispatch) is None or verify_dispatch_consent(session, dispatch) is None):
            raise HttpFixtureInvalid("fixture dispatch is not its original command, consent and worker")
        return value
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        if isinstance(exc, HttpFixtureInvalid):
            raise
        raise HttpFixtureInvalid("original fixture dispatch command cannot be verified") from exc


class PostgresHttpFixtureCommandFence:
    def __init__(self, repository, inputs, authority):
        self.repository, self.inputs = repository, inputs
        self.authority = HttpFixtureCommandAuthority.model_validate(authority.model_dump(mode="json"))

    def command_pin(self, session, scope, phase):
        self.inputs.consent.require_phase(scope, phase)
        intent = self.repository._verify(session, session.get(Intent, self.authority.invocation_id))
        self.repository._matches(self.inputs, intent)
        return {**self.authority.model_dump(mode="json"), "intent_digest": acceptance_digest(intent)}

    def require(self, session, scope, phase, command):
        self.inputs.consent.require_phase(scope, phase)
        if (command.metadata.get("fixture_scope") != asdict(scope) or command.metadata.get("fixture_phase") != phase):
            raise HttpFixtureInvalid("fixture command fence cannot authorize another phase")
        self.repository._require_in_session(session, self.inputs, self.authority)

    def require_existing(self, session, dispatch):
        # Cleanup reads the original independently authorized setup; it does not
        # adopt setup as this cleanup command's own work.
        if self.inputs.selection.operation == "cleanup" and dispatch["phase"] == "setup":
            return
        self.complete(session, dispatch)

    def claim(self, session, dispatch):
        self.inputs.consent.require_phase(HttpFixtureScope(**dispatch["scope"]), dispatch["phase"])
        intent = self.repository._require_in_session(session, self.inputs, self.authority)
        pin = {**self.authority.model_dump(mode="json"), "intent_digest": acceptance_digest(intent)}
        original = session.get(Dispatch, dispatch["claim_id"])
        if (dispatch.get("schema") != FIXTURE_CANONICAL_DISPATCH_SCHEMA or dispatch.get("canonical_command") != pin
                or original is None or original.content_hash != acceptance_digest(dispatch)
                or session.get(Binding, dispatch["claim_id"]) is not None
                or verify_dispatch_ownership(session, dispatch) is None or verify_dispatch_consent(session, dispatch) is None):
            raise HttpFixtureInvalid("fixture command needs this transaction's original consented dispatch")
        payload = {"schema": FIXTURE_DISPATCH_COMMAND_SCHEMA, "claim_id": dispatch["claim_id"],
            "project_id": dispatch["project_id"], **pin, "dispatch_digest": acceptance_digest(dispatch),
            "recorded_at": dispatch["recorded_at"], **{key: False for key in FALSE_AUTHORITIES}}
        session.add(self.repository._row(Binding, payload))

    def complete(self, session, dispatch):
        value = verify_dispatch_command(session, dispatch)
        if value is None or any(value[key] != item for key, item in self.authority.model_dump(mode="json").items()):
            raise HttpFixtureInvalid("fixture command cannot adopt a private or another command's original dispatch")
