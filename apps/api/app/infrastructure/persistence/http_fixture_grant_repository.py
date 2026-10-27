"""PG-clock consent, immutable original ancestry and atomic audit/Outbox."""
from dataclasses import asdict
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.quality_loop.http_fixture_grants import HttpFixtureGrantRequest
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.http_fixture_grant import (
    GRANT_SCHEMA, NATIVE_GRANT_SCHEMA, GRANT_TOOL, GRANT_EVENT, GRANT_EVENT_FIELDS, GRANT_SECONDS, grant_identity, grant_metadata,
)
from ...domain.quality_loop.run_plan import RunPlanIntegrityError
from .db_models import AuditEventRecord, ToolInvocationRecord
from .environment_observation_repository import EnvironmentObservationRepository
from .environment_observation_models import EnvironmentObservationRecord
from .event_outbox_repository import EventOutboxRepository
from .http_fixture_grant_models import HttpFixtureGrantRecord as Record
from .http_fixture_native_grant_models import HttpFixtureNativeGrantRecord
from .http_fixture_recipe_models import HttpFixtureRecipeRecord as Recipe
from .http_fixture_recipe_repository import HttpFixtureRecipeRepository
from .http_fixture_work_repository import PostgresHttpFixtureWorkRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .unit_of_work import session_scope


class HttpFixtureGrantRepository(EnvironmentObservationRepository):
    record_model = Record
    record_tool = GRANT_TOOL

    @staticmethod
    def _clock():
        return func.clock_timestamp()

    @classmethod
    def _canonical(cls, session, request, invocation_id, actor_id, *, historical=False):
        command = super()._canonical(session, request, invocation_id, actor_id, historical=historical)
        if not historical:
            now = session.scalar(select(cls._clock()))
            confirmed = datetime.fromisoformat(command.input_payload["confirmed_at"])
            if not 0 <= (now - confirmed).total_seconds() <= GRANT_SECONDS:
                raise RunPlanIntegrityError("fixture consent confirmation is not fresh by PostgreSQL time")
        return command

    @staticmethod
    def _request(command):
        try:
            return HttpFixtureGrantRequest.model_validate({key: value for key, value in query_payload(command.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}})
        except (ValueError, TypeError, AttributeError):
            raise RunPlanIntegrityError("fixture grant original canonical request invalid") from None

    @staticmethod
    def _parents(session, request):
        recipe = session.get(Recipe, request.recipe_id)
        if (recipe is None or recipe.project_id != request.project_id
                or recipe.artifact_hash != request.recipe_artifact_hash):
            raise RunPlanIntegrityError("fixture grant original registered recipe differs")
        parent = HttpFixtureRecipeRepository._verify(session, recipe)
        if request.policy_revision == NATIVE_GRANT_SCHEMA:
            HttpFixtureGrantRepository._native_parent(session, request, parent)
        return parent

    @staticmethod
    def _native_parent(session, request, recipe):
        row = session.get(EnvironmentObservationRecord, request.environment_record_id)
        value = EnvironmentObservationRepository._verify(session, row)
        command = session.get(ToolInvocationRecord, row.invocation_id)
        if (row.project_id != request.project_id or row.artifact_hash != request.environment_record_artifact_hash
                or any(value[key] != recipe[key] for key in ("run_plan_id", "run_plan_artifact_hash", "plan_digest", "image_revision_id", "manifest_id"))
                or command is None or command.status != "completed"):
            raise RunPlanIntegrityError("native fixture consent must retain its completed original environment and plan")
        result = command.result_payload
        if (type(result) is not dict or result.get("invocation_id") != row.invocation_id
                or result.get("status") != "completed"
                or result.get("object_refs") != ["run_plan_environment:" + row.record_id]
                or acceptance_digest(result.get("run_plan_environment_record")) != acceptance_digest(
                    {"metadata": value, "historical_not_live": True})):
            raise RunPlanIntegrityError("native fixture consent lost its original completed environment receipt")
        return {"record_id": value["record_id"], "artifact_hash": value["artifact_hash"],
            "inventory_hash": value["inventory_hash"], "operator_policy_digest": value["operator_policy_digest"]}

    @staticmethod
    def _native_binding_value(value):
        pin = value["native_environment"]
        return {"schema": "nasus.http-fixture-native-grant.v1", "project_id": value["project_id"],
            "grant_id": value["record_id"], "grant_digest": value["grant_digest"],
            "environment_record_id": pin["record_id"], "environment_record_artifact_hash": pin["artifact_hash"],
            "inventory_hash": pin["inventory_hash"], "operator_policy_digest": pin["operator_policy_digest"]}

    @classmethod
    def _verify_native_binding(cls, session, value, request, parent):
        row = session.get(HttpFixtureNativeGrantRecord, value["record_id"])
        if value["schema"] != NATIVE_GRANT_SCHEMA:
            if row is not None:
                raise RunPlanIntegrityError("native fixture consent cannot downgrade to a legacy grant")
            return
        expected = cls._native_binding_value(value)
        fields = {column.name for column in HttpFixtureNativeGrantRecord.__table__.columns} - {"payload", "content_hash"}
        if (row is None or acceptance_digest(row.payload) != row.content_hash
                or acceptance_digest(row.payload) != acceptance_digest(expected)
                or acceptance_digest({key: getattr(row, key) for key in fields}) != acceptance_digest({key: expected[key] for key in fields})
                or acceptance_digest(value["native_environment"]) != acceptance_digest(cls._native_parent(session, request, parent))):
            raise RunPlanIntegrityError("fixture consent lost its original native inventory registration")

    @staticmethod
    def _require_attempt_anchor(value, parent, scope, actor_id, original_parent):
        fixed = ("project_id", "attempt_id", "parent_digest", "environment_id", "artifact_hash", "inventory_hash", "timeout_ms")
        if (value["actor_id"] != actor_id or any(value["scope"][key] != asdict(scope)[key] for key in fixed)
                or any(parent[key] != original_parent[key] for key in ("run_plan_id", "run_plan_artifact_hash"))):
            raise RunPlanIntegrityError("fixture attempt cannot change its original plan, actor or target")

    @classmethod
    def _verify(cls, session, row):
        if row is None or type(row.payload) is not dict or acceptance_digest(row.payload) != row.content_hash:
            raise RunPlanIntegrityError("original fixture grant metadata invalid")
        value = grant_metadata(row.payload)
        fields = {column.name for column in Record.__table__.columns} - {"payload", "content_hash"}
        if any(getattr(row, key) != value[key] for key in fields):
            raise RunPlanIntegrityError("original fixture grant columns differ from consent bytes")
        request = cls._request(session.get(ToolInvocationRecord, row.invocation_id))
        command = cls._canonical(session, request, row.invocation_id, row.actor_id, historical=True)
        if command.status == "completed":
            result = command.result_payload
            if (type(result) is not dict or result.get("invocation_id") != row.invocation_id
                    or result.get("status") != "completed"
                    or acceptance_digest(result.get("http_fixture_grant")) != acceptance_digest({"metadata": value, "historical_not_live": True})
                    or result.get("object_refs") != ["http_fixture_grant:" + row.record_id]):
                raise RunPlanIntegrityError("completed fixture consent command lost its original result")
        parent = cls._parents(session, request)
        cls._verify_native_binding(session, value, request, parent)
        if (acceptance_digest(row.payload["request"]) != acceptance_digest(request.model_dump(mode="json"))
                or any(row.payload["scope"][key] != parent[field] for key, field in (
                    ("project_id", "project_id"), ("case_id", "case_id"), ("parent_digest", "plan_digest"),
                    ("data_manifest_hash", "data_manifest_hash")))):
            raise RunPlanIntegrityError("fixture grant was rebound from its canonical recipe ancestry")
        return value

    def issue(self, request, scope, source_scope_digest, *, actor_id, invocation_id, require_access, native_environment=None):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            TestDesignScopeRepository._actor(session, request.project_id, actor_id)
            PostgresHttpFixtureWorkRepository._actor_current(session, request.project_id, actor_id)
            row = session.scalar(select(Record).where(Record.invocation_id == invocation_id))
            self._canonical(session, request, invocation_id, actor_id, historical=row is not None)
            parent = self._parents(session, request)
            native = request.policy_revision == NATIVE_GRANT_SCHEMA
            if (native and (acceptance_digest(native_environment) != acceptance_digest(self._native_parent(session, request, parent))
                    or scope.inventory_hash != native_environment["inventory_hash"])
                    or not native and native_environment is not None):
                raise RunPlanIntegrityError("fixture consent cannot substitute an operator policy for its observed instance")
            if row is not None:
                value = self._verify(session, row)
                if (row.actor_id != actor_id or row.scope_digest != scope.digest
                        or row.source_scope_digest != source_scope_digest
                        or row.request_hash != acceptance_digest(request.model_dump(mode="json"))):
                    raise RunPlanIntegrityError("fixture grant replay cannot renew or rebind original consent")
                require_access()
                return value
            # One attempt may include several cases. Its immutable first grant
            # fixes the plan/target/actor; each case separately fixes its recipe.
            anchor = session.scalar(select(Record).where(Record.project_id == request.project_id,
                Record.attempt_id == request.attempt_id).order_by(Record.record_id).limit(1))
            if anchor is not None:
                original = self._verify(session, anchor)
                anchor_parent = self._parents(session, HttpFixtureGrantRequest.model_validate(anchor.payload["request"]))
                self._require_attempt_anchor(original, parent, scope, actor_id, anchor_parent)
                if acceptance_digest(original.get("native_environment")) != acceptance_digest(native_environment):
                    raise RunPlanIntegrityError("fixture attempt cannot replace its original native environment record")
            history = session.scalars(select(Record).where(Record.project_id == request.project_id,
                Record.attempt_id == request.attempt_id, Record.payload["scope"]["case_id"].as_string() == scope.case_id)
                .order_by(Record.record_id).limit(129)).all()
            if len(history) >= 128:
                raise RunPlanIntegrityError("fixture attempt/case consent history exceeds its explicit bound")
            for prior in history:
                self._verify(session, prior)
                if (prior.actor_id != actor_id or prior.scope_digest != scope.digest
                        or prior.recipe_id != request.recipe_id or prior.recipe_artifact_hash != request.recipe_artifact_hash):
                    raise RunPlanIntegrityError("fixture attempt cannot change its original consent scope")
            now = session.scalar(select(self._clock()))
            payload = {"schema": NATIVE_GRANT_SCHEMA if native else GRANT_SCHEMA, "project_id": request.project_id, "record_id": grant_identity(invocation_id),
                "invocation_id": invocation_id, "actor_id": actor_id, "recorded_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=GRANT_SECONDS)).isoformat(), "request": request.model_dump(mode="json"),
                "scope": asdict(scope), "source_scope_digest": source_scope_digest}
            if native:
                payload["native_environment"] = native_environment
            value = grant_metadata(payload)
            require_access()
            self._canonical(session, request, invocation_id, actor_id)
            fields = {column.name for column in Record.__table__.columns} - {"payload", "content_hash"}
            row = Record(**{key: value[key] for key in fields}, payload=payload, content_hash=acceptance_digest(payload))
            session.add(row)
            session.flush()
            if native:
                binding = self._native_binding_value(value)
                columns = {column.name for column in HttpFixtureNativeGrantRecord.__table__.columns} - {"payload", "content_hash"}
                session.add(HttpFixtureNativeGrantRecord(**{key: binding[key] for key in columns},
                    payload=binding, content_hash=acceptance_digest(binding)))
                session.flush()
            self._verify(session, row)
            command = session.get(ToolInvocationRecord, invocation_id)
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=row.recorded_at, actor=actor_id, actor_kind="user",
                action=GRANT_EVENT, entity_type="http_fixture_grant", entity_id=row.record_id, status="issued",
                summary="Independent bounded fixture operation consent recorded; no dispatch or verified coverage.",
                conversation_id=command.conversation_id, tool_invocation_id=invocation_id,
                object_refs=["http_fixture_grant:" + row.record_id], evidence_refs=[], event_metadata={"execution_authorized": False}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=GRANT_EVENT,
                occurred_at=row.recorded_at, correlation_id=request.project_id, entity_type="http_fixture_grant", entity_id=row.record_id,
                conversation_id=command.conversation_id, agent_goal_id=command.input_payload.get("agent_goal_id"),
                entity_version=0, mutation_kind="append", patch={key: value[key] for key in GRANT_EVENT_FIELDS},
                query_keys=[["http-fixture-grants", request.project_id]], snapshot_hint=True), session=session)
            require_access()
            session.flush()
            # Complete ancestry checks can outlive confirmation. Reject the
            # entire new fact transaction rather than renewing its original TTL.
            self._canonical(session, request, invocation_id, actor_id)
            return value

    def read(self, project_id, record_id):
        with session_scope() as session:
            row = session.get(Record, record_id)
            if row is None or row.project_id != project_id:
                raise KeyError("original fixture grant not found")
            self._verify(session, row)
            return row.payload

    def require_live(self, project_id, record_id, *, actor_id, scope, operation, source_scope_digest):
        with session_scope() as session:
            return self.require_live_in_session(session, project_id, record_id, actor_id=actor_id, scope=scope,
                operation=operation, source_scope_digest=source_scope_digest)

    def require_live_in_session(self, session, project_id, record_id, *, actor_id, scope, operation, source_scope_digest):
        """Check the original permission on the caller's dispatch transaction."""
        row = session.get(Record, record_id)
        value = self._verify(session, row)
        PostgresHttpFixtureWorkRepository._actor_current(session, project_id, actor_id)
        command = session.get(ToolInvocationRecord, row.invocation_id)
        now = session.scalar(select(self._clock()))
        if (row.project_id != project_id or row.actor_id != actor_id or row.operation != operation
                or row.source_scope_digest != source_scope_digest or row.scope_digest != scope.digest
                or command.status != "completed" or not datetime.fromisoformat(row.recorded_at) <= now < datetime.fromisoformat(row.expires_at)):
            raise PermissionError("fixture operation consent expired, incomplete or not this exact original scope")
        return value

    @classmethod
    def verify_event(cls, session, event):
        if event.event_type != GRANT_EVENT:
            return
        row = session.get(Record, event.entity_id)
        value = cls._verify(session, row)
        from .run_plan_event_integrity import verify_run_plan_event_envelope
        verify_run_plan_event_envelope(session, event, row, entity_type="http_fixture_grant",
            query_key="http-fixture-grants", error=RunPlanIntegrityError)
        if acceptance_digest(event.patch) != acceptance_digest({key: value[key] for key in GRANT_EVENT_FIELDS}):
            raise RunPlanIntegrityError("fixture grant broadcast cannot replace original consent")
