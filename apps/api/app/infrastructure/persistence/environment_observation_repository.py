"""Original ancestry, native inventory metadata, audit and Outbox in one transaction."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.quality_loop.run_plan_environments import RunPlanEnvironmentQuery
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.environment_observation_record import (
    ENVIRONMENT_RECORD_SCHEMA, ENVIRONMENT_RECORD_TOOL, ENVIRONMENT_RECORD_EVENT, ENVIRONMENT_EVENT_FIELDS,
    FALSE_AUTHORITIES, ZERO_COUNTS, environment_record_metadata, record_identity,
)
from ...domain.quality_loop.native_environment import NativeEnvironmentObservation
from ...domain.quality_loop.run_plan import RunPlanIntegrityError
from .db_models import AuditEventRecord, ToolInvocationRecord
from .environment_observation_models import EnvironmentObservationRecord as Record
from .event_outbox_repository import EventOutboxRepository
from .run_plan_models import RunPlanRecord as Plan
from .run_plan_build_models import RunPlanBuildRecord as Binding
from .run_plan_repository import RunPlanRepository
from .run_plan_build_repository import RunPlanBuildRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .test_design_result_repository import TestDesignResultRepository
from .unit_of_work import session_scope


class EnvironmentObservationRepository:
    record_model = Record
    record_tool = ENVIRONMENT_RECORD_TOOL

    @staticmethod
    def _request(command):
        try:
            return RunPlanEnvironmentQuery.model_validate({key: value for key, value in query_payload(command.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}})
        except (ValueError, TypeError, AttributeError):
            raise RunPlanIntegrityError("environment canonical original request invalid") from None

    @classmethod
    def _canonical(cls, session, request, invocation_id, actor_id, *, historical=False):
        query = select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
        command = session.scalar(query if historical else query.with_for_update())
        if (command is None or command.tool_id != cls.record_tool
                or command.status not in ({"running", "completed", "failed"} if historical else {"running"})
                or command.input_payload.get("confirmed_by_user") is not True
                or command.input_payload.get("confirmed_actor_id") != actor_id or cls._request(command) != request):
            raise RunPlanIntegrityError("environment recording requires its independently confirmed command and actor")
        if not historical:
            try:
                confirmed = datetime.fromisoformat(str(command.input_payload.get("confirmed_at", "")))
                fresh = confirmed.tzinfo is not None and 0 <= (datetime.now(timezone.utc) - confirmed).total_seconds() <= 900
            except (ValueError, OverflowError):
                fresh = False
            if not fresh:
                raise RunPlanIntegrityError("environment confirmation expired or invalid")
        TestDesignResultRepository._project_scope(session, command, request.project_id)
        return command

    @staticmethod
    def _parents(session, request):
        plan, binding = session.get(Plan, request.run_plan_id), session.get(Binding, request.build_binding_id)
        if (plan is None or binding is None or plan.project_id != request.project_id or binding.project_id != request.project_id
                or plan.artifact_hash != request.run_plan_artifact_hash or binding.artifact_hash != request.build_binding_artifact_hash
                or binding.run_plan_id != request.run_plan_id or binding.run_plan_artifact_hash != request.run_plan_artifact_hash):
            raise RunPlanIntegrityError("environment original saved parents differ")
        return RunPlanRepository._verify(session, plan), RunPlanBuildRepository._verify(session, binding)

    @classmethod
    def _verify(cls, session, row):
        if row is None or type(row.payload) is not dict or acceptance_digest(row.payload) != row.content_hash:
            raise RunPlanIntegrityError("registered environment metadata invalid")
        value = row.payload
        fields = {column.name for column in Record.__table__.columns} - {"artifact_ref", "payload", "content_hash"}
        extra = {"schema", "historical_not_live", "native_artifact_attested", "isolation_configuration_attested",
            "durable_native_observation_verified", *FALSE_AUTHORITIES, *ZERO_COUNTS}
        if (set(value) != fields | extra or any(value[key] != getattr(row, key) for key in fields)
                or value["schema"] != ENVIRONMENT_RECORD_SCHEMA or row.status != "recorded"
                or row.record_id != record_identity(row.invocation_id)
                or any(value[key] is not True for key in ("historical_not_live", "native_artifact_attested",
                    "isolation_configuration_attested", "durable_native_observation_verified"))
                or any(value[key] is not False for key in FALSE_AUTHORITIES)
                or any(type(value[key]) is not int or value[key] != 0 for key in ZERO_COUNTS)):
            raise RunPlanIntegrityError("registered environment scope or authority invalid")
        request = cls._request(session.get(ToolInvocationRecord, row.invocation_id))
        cls._canonical(session, request, row.invocation_id, row.actor_id, historical=True)
        plan, binding = cls._parents(session, request)
        if (row.request_hash != acceptance_digest(request.model_dump(mode="json"))
                or any(getattr(row, key) != item for key, item in request.model_dump(mode="json").items())
                or any(getattr(row, key) != plan[key] or binding[key] != plan[key]
                    for key in ("plan_digest", "image_revision_id", "manifest_id"))
                or row.target_artifact_hash != binding["target_artifact_hash"]):
            raise RunPlanIntegrityError("registered environment original ancestry differs")
        return value

    @classmethod
    def _committed(cls, session, request, actor_id, invocation_id):
        row = session.scalar(select(cls.record_model).where(cls.record_model.invocation_id == invocation_id))
        if row is None:
            return None
        value = cls._verify(session, row)
        if row.actor_id != actor_id or row.request_hash != acceptance_digest(request.model_dump(mode="json")):
            raise RunPlanIntegrityError("original environment command cannot be rebound")
        return value

    def committed(self, request, *, actor_id, invocation_id, require_access):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            TestDesignScopeRepository._actor(session, request.project_id, actor_id)
            prior = self._committed(session, request, actor_id, invocation_id)
            self._canonical(session, request, invocation_id, actor_id, historical=prior is not None)
            self._parents(session, request)
            require_access()
            return prior

    def record(self, request, payload, ref, metadata, *, require_access):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            TestDesignScopeRepository._actor(session, request.project_id, metadata["actor_id"])
            prior = self._committed(session, request, metadata["actor_id"], metadata["invocation_id"])
            command = self._canonical(session, request, metadata["invocation_id"], metadata["actor_id"], historical=prior is not None)
            if prior is not None:
                if prior != metadata:
                    raise RunPlanIntegrityError("environment replay cannot replace committed inventory")
                require_access()
                return prior
            plan, binding = self._parents(session, request)
            expected = environment_record_metadata(payload)
            if expected != metadata:
                raise RunPlanIntegrityError("environment metadata differs from original archive")
            original = payload.get("observation")
            if type(original) is not dict or set(original) != {"inventory", "inventory_hash", "observed_at"}:
                raise RunPlanIntegrityError("environment record requires the exact original native inventory")
            observed = NativeEnvironmentObservation(**original)
            if (payload["parents"]["plan_digest"] != plan["plan_digest"]
                    or payload["parents"]["target_artifact_hash"] != binding["target_artifact_hash"]
                    or observed.inventory["project_id"] != request.project_id
                    or observed.inventory["artifact_hash"] != binding["target_artifact_hash"]
                    or any(observed.inventory[key] != metadata[key] for key in ("environment_id", "operator_policy_digest"))):
                raise RunPlanIntegrityError("environment archive differs from canonical parents")
            # The application revalidates original private bytes and live ACL inside this transaction.
            require_access()
            fields = {column.name for column in Record.__table__.columns} - {"artifact_ref", "payload", "content_hash"}
            row = Record(**{key: metadata[key] for key in fields}, artifact_ref=ref,
                payload=metadata, content_hash=acceptance_digest(metadata))
            session.add(row)
            session.flush()
            self._verify(session, row)
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=row.recorded_at, actor=row.actor_id, actor_kind="user",
                action=ENVIRONMENT_RECORD_EVENT, entity_type="run_plan_environment", entity_id=row.record_id, status="recorded",
                summary="Original native inventory recorded; no target execution or verified business coverage.",
                conversation_id=command.conversation_id, tool_invocation_id=command.id,
                object_refs=["run_plan_environment:" + row.record_id], evidence_refs=[],
                event_metadata={"run_plan_id": request.run_plan_id, "execution_authorized": False}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=ENVIRONMENT_RECORD_EVENT,
                occurred_at=row.recorded_at, correlation_id=request.project_id, entity_type="run_plan_environment", entity_id=row.record_id,
                conversation_id=command.conversation_id, agent_goal_id=command.input_payload.get("agent_goal_id"),
                entity_version=0, mutation_kind="append", patch={key: metadata[key] for key in ENVIRONMENT_EVENT_FIELDS},
                query_keys=[["run-plan-environments", request.project_id]], snapshot_hint=True), session=session)
            require_access()
            session.flush()
            return metadata

    def read(self, project_id, record_id):
        with session_scope() as session:
            row = session.get(self.record_model, record_id)
            if row is None or row.project_id != project_id:
                raise KeyError("original environment record not found")
            metadata = self._verify(session, row)
            request = self._request(session.get(ToolInvocationRecord, row.invocation_id))
            return {"metadata": metadata, "artifact_ref": row.artifact_ref, "request": request.model_dump(mode="json")}

    @classmethod
    def verify_event(cls, session, event):
        if event.event_type != ENVIRONMENT_RECORD_EVENT:
            return
        row = session.get(Record, event.entity_id)
        value = cls._verify(session, row)
        from .run_plan_event_integrity import verify_run_plan_event_envelope
        verify_run_plan_event_envelope(session, event, row, entity_type="run_plan_environment",
            query_key="run-plan-environments", error=RunPlanIntegrityError)
        if event.patch != {key: value[key] for key in ENVIRONMENT_EVENT_FIELDS}:
            raise RunPlanIntegrityError("environment event differs from original fact")
