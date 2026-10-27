"""Append locator metadata with the original command, audit and Outbox."""
from uuid import uuid4

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.quality_loop.run_plan_locators import RunPlanLocatorQuery, LocatorSummary
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.http_locator_record import (
    LOCATOR_RECORD_SCHEMA, LOCATOR_RECORD_TOOL, LOCATOR_RECORD_EVENT, LOCATOR_EVENT_FIELDS,
    LOCATOR_FALSE_AUTHORITIES, LOCATOR_ZERO_COUNTS, locator_record_identity, locator_record_metadata,
)
from ...domain.quality_loop.run_plan import RunPlanIntegrityError
from .db_models import AuditEventRecord, ToolInvocationRecord
from .http_locator_models import HttpLocatorRecord as Record
from .environment_observation_repository import EnvironmentObservationRepository
from .event_outbox_repository import EventOutboxRepository
from .run_plan_models import RunPlanRecord as Plan
from .run_plan_repository import RunPlanRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .unit_of_work import session_scope


class HttpLocatorRepository(EnvironmentObservationRepository):
    # Reuse canonical command/actor/TTL and immutable receipt mechanics only.
    record_model = Record
    record_tool = LOCATOR_RECORD_TOOL

    @staticmethod
    def _request(command):
        try:
            return RunPlanLocatorQuery.model_validate({key: value for key, value in query_payload(command.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}})
        except (ValueError, TypeError, AttributeError):
            raise RunPlanIntegrityError("locator canonical original request invalid") from None

    @staticmethod
    def _parents(session, request):
        plan = session.get(Plan, request.run_plan_id)
        if plan is None or plan.project_id != request.project_id or plan.artifact_hash != request.run_plan_artifact_hash:
            raise RunPlanIntegrityError("locator original saved plan differs")
        return RunPlanRepository._verify(session, plan)

    @classmethod
    def _verify(cls, session, row):
        if row is None or type(row.payload) is not dict or acceptance_digest(row.payload) != row.content_hash:
            raise RunPlanIntegrityError("registered locator metadata invalid")
        value = row.payload
        fields = {column.name for column in Record.__table__.columns} - {"artifact_ref", "payload", "content_hash"}
        true_flags = ("historical_not_live", "source_bytes_verified", "durable_locator_evidence_verified")
        if (set(value) != fields | {"schema", "summary", *true_flags, *LOCATOR_FALSE_AUTHORITIES, *LOCATOR_ZERO_COUNTS}
                or any(value[key] != getattr(row, key) for key in fields)
                or value["schema"] != LOCATOR_RECORD_SCHEMA or row.status != "recorded"
                or row.record_id != locator_record_identity(row.invocation_id)
                or any(value[key] is not True for key in true_flags)
                or any(value[key] is not False for key in LOCATOR_FALSE_AUTHORITIES)
                or any(type(value[key]) is not int or value[key] != 0 for key in LOCATOR_ZERO_COUNTS)):
            raise RunPlanIntegrityError("registered locator scope or authority invalid")
        LocatorSummary.model_validate(value["summary"])
        request = cls._request(session.get(ToolInvocationRecord, row.invocation_id))
        cls._canonical(session, request, row.invocation_id, row.actor_id, historical=True)
        parent = cls._parents(session, request)
        if (row.request_hash != acceptance_digest(request.model_dump(mode="json"))
                or any(getattr(row, key) != item for key, item in request.model_dump(mode="json").items())
                or any(getattr(row, key) != parent[key] for key in ("plan_digest", "image_revision_id", "manifest_id"))):
            raise RunPlanIntegrityError("registered locator original ancestry differs")
        return value

    def record(self, request, payload, ref, metadata, *, require_access):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            TestDesignScopeRepository._actor(session, request.project_id, metadata["actor_id"])
            prior = self._committed(session, request, metadata["actor_id"], metadata["invocation_id"])
            command = self._canonical(session, request, metadata["invocation_id"], metadata["actor_id"], historical=prior is not None)
            if prior is not None:
                if prior != metadata:
                    raise RunPlanIntegrityError("locator replay cannot replace committed original bytes")
                require_access()
                return prior
            parent = self._parents(session, request)
            if (locator_record_metadata(payload) != metadata
                    or any(metadata[key] != parent[key] for key in ("plan_digest", "image_revision_id", "manifest_id"))):
                raise RunPlanIntegrityError("locator archive differs from canonical ancestry")
            require_access()
            fields = {column.name for column in Record.__table__.columns} - {"artifact_ref", "payload", "content_hash"}
            row = Record(**{key: metadata[key] for key in fields}, artifact_ref=ref, payload=metadata,
                content_hash=acceptance_digest(metadata))
            session.add(row)
            session.flush()
            self._verify(session, row)
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=row.recorded_at, actor=row.actor_id, actor_kind="user",
                action=LOCATOR_RECORD_EVENT, entity_type="run_plan_locators", entity_id=row.record_id, status="recorded",
                summary="Fixed original source locators archived; no runtime dispatch or business coverage.",
                conversation_id=command.conversation_id, tool_invocation_id=command.id,
                object_refs=["run_plan_locators:" + row.record_id], evidence_refs=[],
                event_metadata={"run_plan_id": request.run_plan_id, "execution_authorized": False}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=LOCATOR_RECORD_EVENT,
                occurred_at=row.recorded_at, correlation_id=request.project_id, entity_type="run_plan_locators", entity_id=row.record_id,
                conversation_id=command.conversation_id, agent_goal_id=command.input_payload.get("agent_goal_id"),
                entity_version=0, mutation_kind="append", patch={key: metadata[key] for key in LOCATOR_EVENT_FIELDS},
                query_keys=[["run-plan-locators", request.project_id]], snapshot_hint=True), session=session)
            require_access()
            session.flush()
            return metadata

    @classmethod
    def verify_event(cls, session, event):
        if event.event_type != LOCATOR_RECORD_EVENT:
            return
        row = session.get(Record, event.entity_id)
        value = cls._verify(session, row)
        from .run_plan_event_integrity import verify_run_plan_event_envelope
        verify_run_plan_event_envelope(session, event, row, entity_type="run_plan_locators",
            query_key="run-plan-locators", error=RunPlanIntegrityError)
        if event.patch != {key: value[key] for key in LOCATOR_EVENT_FIELDS}:
            raise RunPlanIntegrityError("locator event differs from original fact")
