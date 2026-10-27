"""Original dispatch durability; public jobs additionally require all three fences."""
from copy import deepcopy
from contextlib import nullcontext
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from ...application.platform.tool_models import EventPayload
from ...application.quality_loop.http_fixture_journal_access import HttpFixtureSavedPlanAccessPort, HttpFixtureExecutionArtifactPort
from ...application.quality_loop.http_fixtures import HttpFixtureDispatchAlreadyClaimed, HttpFixturePhaseRecord
from ...application.quality_loop.http_fixture_work import HttpFixtureTransactionFencePort
from ...application.quality_loop.http_fixture_dispatch_consent import HttpFixtureTransactionConsentPort
from ...application.quality_loop.http_fixture_commands import HttpFixtureTransactionCommandPort
from ...application.quality_loop.http_fixture_commands import HttpFixtureCommandAuthority
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.http_fixtures import HttpFixtureInvalid
from ...domain.quality_loop.http_fixture_command import FIXTURE_CANONICAL_DISPATCH_SCHEMA
from ..runner.http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from ..runner.request_wire import runner_request_hash
from .db_models import AuditEventRecord, ToolInvocationRecord
from .database import engine
from .event_outbox_repository import EventOutboxRepository
from .http_fixture_journal_models import HttpFixtureDispatchRecord as Dispatch, HttpFixtureResultRecord as Result
from .http_fixture_work_repository import verify_dispatch_ownership
from .http_fixture_work_models import HttpFixtureDispatchOwnershipRecord
from .http_fixture_dispatch_consent_models import HttpFixtureDispatchConsentRecord
from .http_fixture_dispatch_consent_repository import verify_dispatch_consent
from .http_fixture_command_models import HttpFixtureDispatchCommandRecord
from .http_fixture_command_repository import verify_dispatch_command, require_private_fixture_work
from .native_build_repository import NativeBuildRepository
from .run_plan_models import RunPlanRecord
from .run_plan_repository import RunPlanRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .unit_of_work import session_scope


FALSE_AUTHORITY = ("execution_authorized", "canonical_execution_committed", "business_coverage_verified", "baseline_restored")


class PostgresHttpFixtureDispatchJournal:
    """A required caller fence is checked inside every write transaction.

    Public jobs compose this adapter only through the owned runtime factory.
    Saved-plan access, an administrator role and a journal are not dispatch consent.
    """
    def __init__(self, access: HttpFixtureSavedPlanAccessPort, artifacts: HttpFixtureExecutionArtifactPort, *, actor_id,
                 work_fence: HttpFixtureTransactionFencePort = None, consent_fence: HttpFixtureTransactionConsentPort = None,
                 command_fence: HttpFixtureTransactionCommandPort = None):
        if engine.dialect.name != "postgresql":
            raise HttpFixtureInvalid("backend fixture journals require PostgreSQL")
        if type(actor_id) is not str or not 1 <= len(actor_id) <= 128:
            raise HttpFixtureInvalid("fixture journal requires an explicit current actor")
        if consent_fence is not None and work_fence is None:
            raise HttpFixtureInvalid("fixture permission cannot bypass original worker ownership")
        if command_fence is not None and (work_fence is None or consent_fence is None):
            raise HttpFixtureInvalid("fixture command cannot bypass original worker and operation consent")
        self.access, self.artifacts, self.actor_id = access, artifacts, actor_id
        self.work_fence = work_fence
        self.consent_fence = consent_fence
        self.command_fence = command_fence
        self.verifier = OwnedHttpFixtureObservationVerifier()

    def _read_session(self):
        reader = getattr(self.access, "verified_read_session", None)
        return reader() if callable(reader) else nullcontext()

    def verified_read_session(self):
        # A phase may reuse immutable proof across its original guard calls.
        return self._read_session()

    @staticmethod
    def _identity(scope, phase):
        return "fixture_" + acceptance_digest([scope.project_id, scope.attempt_id, scope.case_id, phase])[7:]

    @staticmethod
    def _value(row):
        if row is None:
            return None
        columns = {column.name for column in row.__table__.columns} - {"payload", "content_hash"}
        if (type(row.payload) is not dict or acceptance_digest(row.payload) != row.content_hash
                or any(row.payload.get(key) != getattr(row, key) for key in columns)
                or any(row.payload.get(key) is not False for key in FALSE_AUTHORITY)):
            raise HttpFixtureInvalid("fixture journal immutable metadata differs")
        return deepcopy(row.payload)

    @staticmethod
    def _parent(session, parent):
        row = session.get(RunPlanRecord, parent["run_plan_id"])
        if (row is None or row.project_id != parent["project_id"]
                or row.artifact_hash != parent["run_plan_artifact_hash"] or row.plan_digest != parent["plan_digest"]):
            raise HttpFixtureInvalid("fixture journal parent is not the original registered RunPlan")
        RunPlanRepository._verify(session, row)
        return row

    def _lock(self, session, parent):
        TestDesignScopeRepository._lock(session, parent["project_id"])
        NativeBuildRepository._actor(session, parent["project_id"], self.actor_id)
        return self._parent(session, parent)

    def _expected(self, scope, phase, *, read_only=False):
        receipt = None
        if type(phase) is str and phase.startswith("cleanup:"):
            original = self.inspect(scope, "setup", read_only=read_only)
            if original is None or original.execution is None:
                raise HttpFixtureInvalid("cleanup cannot invent an unobserved original setup resource")
            receipt = self.verifier.verify(original.command, original.execution,
                environment_id=scope.environment_id, inventory_hash=scope.inventory_hash)
        return self.access.command(scope, phase, setup_receipt=receipt)

    def _records(self, session, parent, scope, phase, command):
        ident = self._identity(scope, phase)
        reserved = self._value(session.get(Dispatch, ident))
        completed = self._value(session.get(Result, ident))
        if reserved is None:
            if (completed is not None or session.get(HttpFixtureDispatchOwnershipRecord, ident) is not None
                    or session.get(HttpFixtureDispatchConsentRecord, ident) is not None
                    or session.get(HttpFixtureDispatchCommandRecord, ident) is not None):
                raise HttpFixtureInvalid("fixture history lacks its original dispatch; never redispatch its unknown effect")
            return None, None
        plan = session.get(RunPlanRecord, parent["run_plan_id"])
        expected = dict(project_id=scope.project_id, attempt_id=scope.attempt_id, case_id=scope.case_id,
            phase=phase, parent=parent, scope=asdict(scope), scope_digest=scope.digest,
            command_digest=acceptance_digest(asdict(command)), request_hash=runner_request_hash(command),
            **{key: parent[key] for key in ("run_plan_id", "run_plan_artifact_hash", "plan_digest")},
            image_revision_id=plan.image_revision_id, manifest_id=plan.manifest_id)
        if (reserved.get("schema") not in {"nasus.http-fixture-dispatch.v1", "nasus.http-fixture-dispatch.v2", "nasus.http-fixture-dispatch.v3", FIXTURE_CANONICAL_DISPATCH_SCHEMA}
                or reserved["status"] != "reserved"
                or any(reserved.get(key) != value for key, value in expected.items())
                or reserved.get("command") != self._command_value(command)):
            raise HttpFixtureInvalid("fixture original attempt cannot be rebound")
        if completed is not None and (completed.get("schema") != "nasus.http-fixture-result.v1"
                or completed["dispatch_digest"] != acceptance_digest(reserved)
                or completed["actor_id"] != reserved["actor_id"]):
            raise HttpFixtureInvalid("fixture result ancestry differs from the original dispatch")
        verify_dispatch_ownership(session, reserved)
        verify_dispatch_consent(session, reserved)
        verify_dispatch_command(session, reserved)
        if self.command_fence is not None:
            self.command_fence.require_existing(session, reserved)
        return reserved, completed

    @staticmethod
    def _command_value(command):
        value = asdict(command)
        value["steps"] = list(value["steps"])
        return value

    @staticmethod
    def _row(model, value):
        columns = {column.name for column in model.__table__.columns} - {"payload", "content_hash"}
        return model(**{key: value[key] for key in columns}, payload=value, content_hash=acceptance_digest(value))

    @staticmethod
    def _event(session, value, *, completed, command_invocation_id=None):
        event_type = "quality.http_fixture.result_recorded" if completed else "quality.http_fixture.dispatch_reserved"
        summary = "Private original fixture journal; no execution consent or verified business coverage."
        if value.get("schema") == "nasus.http-fixture-dispatch.v3":
            summary = "Original worker/operation consent recorded; no canonical execution or verified business coverage."
        if command_invocation_id is not None:
            summary = "Original fixture command observation; no business execution or verified coverage."
        command = session.get(ToolInvocationRecord, command_invocation_id) if command_invocation_id is not None else None
        session.add(AuditEventRecord(id=str(uuid4()), occurred_at=value["recorded_at"], actor=value["actor_id"],
            actor_kind="user", action=event_type, entity_type="http_fixture_journal", entity_id=value["claim_id"],
            status=value["status"], summary=summary,
            conversation_id=command.conversation_id if command is not None else None,
            agent_goal_id=command.input_payload.get("agent_goal_id") if command is not None else None,
            tool_invocation_id=command_invocation_id, object_refs=["http_fixture_journal:" + value["claim_id"]],
            evidence_refs=[], event_metadata={"execution_authorized": False, "canonical_execution_committed": False}))
        EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=event_type,
            occurred_at=value["recorded_at"], correlation_id=value["project_id"], entity_type="http_fixture_journal",
            entity_id=value["claim_id"], entity_version=1 if completed else 0, mutation_kind="append",
            conversation_id=command.conversation_id if command is not None else None,
            agent_goal_id=command.input_payload.get("agent_goal_id") if command is not None else None,
            patch={key: value[key] for key in ("project_id", "claim_id", "status")},
            query_keys=[["http-fixture-journal", value["project_id"]]], snapshot_hint=True), session=session)

    def inspect(self, scope, phase, *, original_command=None, read_only=False):
        with self._read_session():
            return self._inspect(scope, phase, original_command=original_command, read_only=read_only)

    def _inspect(self, scope, phase, *, original_command=None, read_only=False):
        if type(read_only) is not bool or read_only and any(value is not None for value in
                (self.work_fence, self.consent_fence, self.command_fence)):
            raise HttpFixtureInvalid("readonly original history cannot act as a live worker fence")
        if original_command is not None:
            original_command = HttpFixtureCommandAuthority.model_validate(original_command.model_dump(mode="json"))
            if phase != "setup":
                raise HttpFixtureInvalid("a setup command cannot adopt an independently dispatched cleanup")
        parent = self.access.require_scope(scope)
        command = self._expected(scope, phase, read_only=read_only)
        with session_scope() as session:
            if read_only:
                # The caller may already hold the project's write fence in a
                # different session. Immutable reads must not reacquire it.
                NativeBuildRepository._actor(session, parent["project_id"], self.actor_id, lock=False)
                self._parent(session, parent)
            else:
                self._lock(session, parent)
            self.access.require_scope(scope)
            reserved, completed = self._records(session, parent, scope, phase, command)
            if reserved is None:
                if read_only:
                    NativeBuildRepository._actor(session, parent["project_id"], self.actor_id, lock=False)
                return None
            if original_command is not None:
                pin = reserved.get("canonical_command")
                if (reserved["schema"] != FIXTURE_CANONICAL_DISPATCH_SCHEMA or type(pin) is not dict
                        or any(pin.get(key) != value for key, value in original_command.model_dump(mode="json").items())):
                    raise HttpFixtureInvalid("selected setup cannot adopt another command's original dispatch")
            if completed is None:
                if read_only:
                    self.access.require_scope(scope)
                    NativeBuildRepository._actor(session, parent["project_id"], self.actor_id, lock=False)
                return HttpFixturePhaseRecord(command, None)
            execution = self.artifacts.read(parent, scope, phase, command, completed["artifact_ref"], completed["artifact_hash"])
            receipt = self.verifier.verify(command, execution, environment_id=scope.environment_id, inventory_hash=scope.inventory_hash)
            if completed["receipt_digest"] != acceptance_digest(receipt) or completed["status"] != execution.result.status:
                raise HttpFixtureInvalid("fixture stored outcome differs from the original native response")
            self.access.require_scope(scope)
            if read_only:
                NativeBuildRepository._actor(session, parent["project_id"], self.actor_id, lock=False)
            return HttpFixturePhaseRecord(command, execution)

    def claim(self, scope, phase, command, *, require_current):
        with self._read_session():
            return self._claim(scope, phase, command, require_current=require_current)

    def _claim(self, scope, phase, command, *, require_current):
        require_current()
        parent = self.access.require_scope(scope)
        if command != self._expected(scope, phase):
            raise HttpFixtureInvalid("fixture dispatch command is outside the original manifest")
        preflight = getattr(self.access, "require_dispatch", None)
        if callable(preflight):
            # Native access must verify its exact live epoch before any claim is
            # staged. Runner still rechecks immediately around the HTTP request.
            preflight(scope, phase, command, require_work=require_current)
            require_current()
        with session_scope() as session:
            plan = self._lock(session, parent)
            self.access.require_scope(scope)
            require_current()
            if self.work_fence is not None:
                self.work_fence.require(session, scope, phase, command)
            if self.consent_fence is not None:
                self.consent_fence.require(session, scope, phase, command)
            if self.command_fence is not None:
                self.command_fence.require(session, scope, phase, command)
            else:
                require_private_fixture_work(session, scope, phase)
            prior, _ = self._records(session, parent, scope, phase, command)
            if prior is not None:
                raise HttpFixtureDispatchAlreadyClaimed("original fixture phase is already durably reserved")
            value = {"schema": "nasus.http-fixture-dispatch.v1", "claim_id": self._identity(scope, phase),
                "project_id": scope.project_id, "attempt_id": scope.attempt_id, "case_id": scope.case_id, "phase": phase,
                **{key: parent[key] for key in ("run_plan_id", "run_plan_artifact_hash", "plan_digest")},
                "image_revision_id": plan.image_revision_id, "manifest_id": plan.manifest_id,
                "parent": parent, "scope": asdict(scope), "scope_digest": scope.digest,
                "command": self._command_value(command), "command_digest": acceptance_digest(asdict(command)),
                "request_hash": runner_request_hash(command), "actor_id": self.actor_id,
                "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "reserved",
                **{key: False for key in FALSE_AUTHORITY}}
            if self.work_fence is not None:
                value.update(schema="nasus.http-fixture-dispatch.v2",
                    work_ownership=self.work_fence.ownership_pin(scope, phase))
            if self.consent_fence is not None:
                value.update(schema="nasus.http-fixture-dispatch.v3",
                    operation_consent=self.consent_fence.consent_pin(scope, phase))
            if self.command_fence is not None:
                value.update(schema=FIXTURE_CANONICAL_DISPATCH_SCHEMA,
                    canonical_command=self.command_fence.command_pin(session, scope, phase))
            session.add(self._row(Dispatch, value))
            self._event(session, value, completed=False,
                command_invocation_id=value.get("canonical_command", {}).get("invocation_id"))
            session.flush()
            if self.work_fence is not None:
                self.work_fence.claim(session, value)
                session.flush()
                self.work_fence.require(session, scope, phase, command)
            if self.consent_fence is not None:
                self.consent_fence.claim(session, value)
                session.flush()
                verify_dispatch_consent(session, value)
                self.consent_fence.require(session, scope, phase, command)
            if self.command_fence is not None:
                self.command_fence.claim(session, value)
                session.flush()
                verify_dispatch_command(session, value)
                self.command_fence.require(session, scope, phase, command)
            self.access.require_scope(scope)
            require_current()

    def complete(self, scope, phase, command, execution, *, require_current):
        with self._read_session():
            return self._complete(scope, phase, command, execution, require_current=require_current)

    def _complete(self, scope, phase, command, execution, *, require_current):
        require_current()
        parent = self.access.require_scope(scope)
        if command != self._expected(scope, phase):
            raise HttpFixtureInvalid("fixture result command is outside the original manifest")
        receipt = self.verifier.verify(command, execution, environment_id=scope.environment_id, inventory_hash=scope.inventory_hash)
        ref, digest = self.artifacts.put(parent, scope, phase, command, execution)
        require_current()
        with session_scope() as session:
            self._lock(session, parent)
            self.access.require_scope(scope)
            require_current()
            if self.work_fence is not None:
                self.work_fence.require(session, scope, phase, command)
            if self.consent_fence is not None:
                self.consent_fence.require(session, scope, phase, command)
            if self.command_fence is not None:
                self.command_fence.require(session, scope, phase, command)
            reserved, prior = self._records(session, parent, scope, phase, command)
            if reserved is None or reserved["actor_id"] != self.actor_id:
                raise HttpFixtureInvalid("fixture completion lacks this actor's original dispatch")
            if self.work_fence is not None:
                self.work_fence.complete(session, reserved)
            elif verify_dispatch_ownership(session, reserved) is not None:
                raise HttpFixtureInvalid("leased dispatch cannot bypass its durable original ownership")
            if self.consent_fence is not None:
                self.consent_fence.complete(session, reserved)
            elif verify_dispatch_consent(session, reserved) is not None:
                raise HttpFixtureInvalid("consented dispatch cannot bypass its original operation permission")
            if self.command_fence is not None:
                self.command_fence.complete(session, reserved)
            elif verify_dispatch_command(session, reserved) is not None:
                raise HttpFixtureInvalid("command-bound dispatch cannot bypass its original canonical authority")
            if prior is not None:
                if (prior["artifact_ref"] != ref or prior["artifact_hash"] != digest
                        or prior["receipt_digest"] != acceptance_digest(receipt) or prior["status"] != execution.result.status):
                    raise HttpFixtureInvalid("fixture completion cannot replace its original outcome")
                return
            value = {"schema": "nasus.http-fixture-result.v1", "claim_id": reserved["claim_id"],
                "project_id": scope.project_id, "actor_id": self.actor_id, "recorded_at": datetime.now(timezone.utc).isoformat(),
                "status": execution.result.status, "dispatch_digest": acceptance_digest(reserved),
                "receipt_digest": acceptance_digest(receipt), "artifact_ref": ref, "artifact_hash": digest,
                **{key: False for key in FALSE_AUTHORITY}}
            session.add(self._row(Result, value))
            self._event(session, value, completed=True,
                command_invocation_id=reserved.get("canonical_command", {}).get("invocation_id"))
            session.flush()
            self._records(session, parent, scope, phase, command)
            if self.work_fence is not None:
                self.work_fence.require(session, scope, phase, command)
                self.work_fence.complete(session, reserved)
            if self.consent_fence is not None:
                self.consent_fence.require(session, scope, phase, command)
                self.consent_fence.complete(session, reserved)
            if self.command_fence is not None:
                self.command_fence.require(session, scope, phase, command)
                self.command_fence.complete(session, reserved)
            self.access.require_scope(scope)
            require_current()
