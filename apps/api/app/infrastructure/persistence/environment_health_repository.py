"""Append-only health metadata and its original command, audit and Outbox."""
from uuid import uuid4

from ...application.platform.tool_models import EventPayload
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.environment_health_record import (
    HEALTH_RECORD_SCHEMA, HEALTH_RECORD_TOOL, HEALTH_RECORD_EVENT, HEALTH_EVENT_FIELDS,
    HEALTH_FALSE_AUTHORITIES, ZERO_COUNTS, health_record_identity, health_record_metadata,
)
from ...domain.quality_loop.run_plan import RunPlanIntegrityError
from .db_models import AuditEventRecord, ToolInvocationRecord
from .environment_health_models import EnvironmentHealthRecord as Record
from .environment_observation_repository import EnvironmentObservationRepository
from .event_outbox_repository import EventOutboxRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .unit_of_work import session_scope


class EnvironmentHealthRepository(EnvironmentObservationRepository):
    record_model = Record
    record_tool = HEALTH_RECORD_TOOL

    @classmethod
    def _verify(cls, session, row):
        if row is None or type(row.payload) is not dict or acceptance_digest(row.payload) != row.content_hash:
            raise RunPlanIntegrityError("registered health metadata invalid")
        value = row.payload
        fields = {column.name for column in Record.__table__.columns} - {"artifact_ref", "payload", "content_hash"}
        true_flags = ("historical_not_live", "native_artifact_attested", "isolation_configuration_attested", "durable_native_observation_verified")
        extra = {"schema", "health_checks", *true_flags, *HEALTH_FALSE_AUTHORITIES, *ZERO_COUNTS}
        if (set(value) != fields | extra or any(value[key] != getattr(row, key) for key in fields)
                or value["schema"] != HEALTH_RECORD_SCHEMA or row.status != "recorded"
                or row.record_id != health_record_identity(row.invocation_id)
                or any(value[key] is not True for key in true_flags)
                or any(value[key] is not False for key in HEALTH_FALSE_AUTHORITIES)
                or any(type(value[key]) is not int or value[key] != 0 for key in ZERO_COUNTS)
                or any(type(value[key]) is not bool for key in ("dependency_health_verified", "target_health_verified"))
                or type(value["health_checks"]) is not list or len(value["health_checks"]) != 3):
            raise RunPlanIntegrityError("registered health scope or authority invalid")
        request = cls._request(session.get(ToolInvocationRecord, row.invocation_id))
        cls._canonical(session, request, row.invocation_id, row.actor_id, historical=True)
        plan, binding = cls._parents(session, request)
        if (row.request_hash != acceptance_digest(request.model_dump(mode="json"))
                or any(getattr(row, key) != item for key, item in request.model_dump(mode="json").items())
                or any(getattr(row, key) != plan[key] or binding[key] != plan[key]
                    for key in ("plan_digest", "image_revision_id", "manifest_id"))
                or row.target_artifact_hash != binding["target_artifact_hash"]):
            raise RunPlanIntegrityError("registered health original ancestry differs")
        return value

    def record(self, request, payload, ref, metadata, *, require_access):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            TestDesignScopeRepository._actor(session, request.project_id, metadata["actor_id"])
            prior = self._committed(session, request, metadata["actor_id"], metadata["invocation_id"])
            command = self._canonical(session, request, metadata["invocation_id"], metadata["actor_id"], historical=prior is not None)
            if prior is not None:
                if prior != metadata:
                    raise RunPlanIntegrityError("health replay cannot replace committed original bytes")
                require_access()
                return prior
            plan, binding = self._parents(session, request)
            if (health_record_metadata(payload) != metadata
                    or payload["parents"]["plan_digest"] != plan["plan_digest"]
                    or payload["parents"]["target_artifact_hash"] != binding["target_artifact_hash"]):
                raise RunPlanIntegrityError("health archive differs from original canonical ancestry")
            require_access()
            fields = {column.name for column in Record.__table__.columns} - {"artifact_ref", "payload", "content_hash"}
            row = Record(**{key: metadata[key] for key in fields}, artifact_ref=ref,
                payload=metadata, content_hash=acceptance_digest(metadata))
            session.add(row)
            session.flush()
            self._verify(session, row)
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=row.recorded_at, actor=row.actor_id, actor_kind="user",
                action=HEALTH_RECORD_EVENT, entity_type="run_plan_health", entity_id=row.record_id, status="recorded",
                summary="Original instance health recorded; no target test execution or business coverage.",
                conversation_id=command.conversation_id, tool_invocation_id=command.id,
                object_refs=["run_plan_health:" + row.record_id], evidence_refs=[],
                event_metadata={"run_plan_id": request.run_plan_id, "execution_authorized": False}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=HEALTH_RECORD_EVENT,
                occurred_at=row.recorded_at, correlation_id=request.project_id, entity_type="run_plan_health", entity_id=row.record_id,
                conversation_id=command.conversation_id, agent_goal_id=command.input_payload.get("agent_goal_id"),
                entity_version=0, mutation_kind="append", patch={key: metadata[key] for key in HEALTH_EVENT_FIELDS},
                query_keys=[["run-plan-health", request.project_id]], snapshot_hint=True), session=session)
            require_access()
            session.flush()
            return metadata

    @classmethod
    def verify_event(cls, session, event):
        if event.event_type != HEALTH_RECORD_EVENT:
            return
        row = session.get(Record, event.entity_id)
        value = cls._verify(session, row)
        from .run_plan_event_integrity import verify_run_plan_event_envelope
        verify_run_plan_event_envelope(session, event, row, entity_type="run_plan_health",
            query_key="run-plan-health", error=RunPlanIntegrityError)
        if event.patch != {key: value[key] for key in HEALTH_EVENT_FIELDS}:
            raise RunPlanIntegrityError("health event differs from original fact")
