"""Exact original observations, complete roster, audit and Outbox in one transaction."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.quality_loop.run_plan_observation_records import ObservationRecordRequest, OBSERVATION_RECORD_TOOL
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.run_plan_observation_record import observation_record_metadata
from ...domain.quality_loop.run_plan_observations import RunPlanObservationInvalid
from .db_models import AuditEventRecord, ToolInvocationRecord
from .event_outbox_repository import EventOutboxRepository
from .run_plan_models import RunPlanRecord as Plan
from .run_plan_observation_models import RunPlanObservationRecord as Record, RunPlanCaseObservationRecord as Member
from .run_plan_repository import RunPlanRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .test_design_result_repository import TestDesignResultRepository
from .unit_of_work import session_scope


EVENT_TYPE = "quality.run_plan.observations_recorded"
EVENT_FIELDS = ("project_id", "record_id", "run_plan_id", "collection_digest", "status")
FALSE_AUTHORITY = ("execution_authorized", "target_build_verified", "business_coverage_verified", "canonical_execution_committed")
ZERO_COVERAGE = ("automated_count", "executed_on_target_count", "passed_count")


class RunPlanObservationRepository:
    @staticmethod
    def _request(command):
        try:
            return ObservationRecordRequest.model_validate({key: value for key, value in query_payload(command.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}})
        except (ValueError, TypeError, AttributeError):
            raise RunPlanObservationInvalid("observation canonical original request invalid") from None

    @classmethod
    def _canonical(cls, session, request, invocation_id, actor_id, *, historical=False):
        query = select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
        command = session.scalar(query if historical else query.with_for_update())
        if (command is None or command.tool_id != OBSERVATION_RECORD_TOOL
                or command.status not in ({"running", "completed", "failed"} if historical else {"running"})
                or command.input_payload.get("confirmed_by_user") is not True
                or command.input_payload.get("confirmed_actor_id") != actor_id or cls._request(command) != request):
            raise RunPlanObservationInvalid("observation recording requires its exact independently confirmed command and actor")
        if not historical:
            try:
                confirmed = datetime.fromisoformat(str(command.input_payload.get("confirmed_at", "")))
                fresh = confirmed.tzinfo is not None and 0 <= (datetime.now(timezone.utc) - confirmed).total_seconds() <= 900
            except (ValueError, OverflowError):
                fresh = False
            if not fresh:
                raise RunPlanObservationInvalid("observation recording confirmation expired or invalid")
        TestDesignResultRepository._project_scope(session, command, request.project_id)
        return command

    @staticmethod
    def _parent(session, request):
        row = session.get(Plan, request.run_plan_id)
        if (row is None or row.project_id != request.project_id or row.artifact_hash != request.run_plan_artifact_hash
                or row.plan_digest != request.plan_digest):
            raise RunPlanObservationInvalid("observation original saved plan registration differs")
        return RunPlanRepository._verify(session, row)

    @staticmethod
    def _value(row, model):
        fields = {column.name for column in model.__table__.columns} - {"artifact_ref", "payload", "content_hash"}
        if (row is None or type(row.payload) is not dict or acceptance_digest(row.payload) != row.content_hash
                or any(row.payload.get(key) != getattr(row, key) for key in fields)):
            raise RunPlanObservationInvalid("registered observation metadata invalid")
        return row.payload

    @classmethod
    def _verify(cls, session, row):
        value = cls._value(row, Record)
        request = cls._request(session.get(ToolInvocationRecord, row.invocation_id))
        cls._canonical(session, request, row.invocation_id, row.actor_id, historical=True)
        parent = cls._parent(session, request)
        if (row.status != "recorded" or any(value.get(key) is not False for key in FALSE_AUTHORITY)
                or any(type(value.get(key)) is not int or value[key] != 0 for key in ZERO_COVERAGE)
                or row.request_hash != acceptance_digest(request.model_dump(mode="json"))
                or row.artifact_hash != request.observation_artifact_hash
                or any(getattr(row, key) != getattr(request, key) for key in
                    ("project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "collection_digest", "run_id"))
                or any(getattr(row, key) != parent[key] for key in ("image_revision_id", "manifest_id"))
                or type(row.case_count) is not int or not 1 <= row.case_count <= 512):
            raise RunPlanObservationInvalid("observation registration cannot change its original ancestry or authority")
        rows = session.scalars(select(Member).where(Member.record_id == row.record_id).order_by(Member.ordinal).limit(513)).all()
        members = [cls._value(item, Member) for item in rows]
        if (len(members) != row.case_count or value.get("members") != members
                or [item["ordinal"] for item in members] != list(range(row.case_count))
                or len({item["case_id"] for item in members}) != row.case_count
                or any(item["project_id"] != row.project_id or item["record_id"] != row.record_id for item in members)):
            raise RunPlanObservationInvalid("complete original observation roster missing or changed")
        totals = {"observed_case_count": sum(item["observation_digest"] is not None for item in members),
            "outcome_unknown_case_count": sum(item["status"] == "outcome_unknown" for item in members),
            "no_result_case_count": sum(item["status"] in {"not_observed", "not_executed"} for item in members),
            "passed_observation_count": sum(item["status"] == "passed" for item in members),
            "failed_observation_count": sum(item["status"] == "failed" for item in members)}
        if any(type(value.get(key)) is not int or value[key] != total for key, total in totals.items()):
            raise RunPlanObservationInvalid("observation counts differ from original members")
        return value

    @classmethod
    def _committed(cls, session, request, actor_id, invocation_id):
        row = session.scalar(select(Record).where(Record.invocation_id == invocation_id))
        if row is None:
            return None
        value = cls._verify(session, row)
        if row.actor_id != actor_id or row.request_hash != acceptance_digest(request.model_dump(mode="json")):
            raise RunPlanObservationInvalid("original observation command cannot be rebound")
        return value

    def committed(self, request, *, actor_id, invocation_id, require_access):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            TestDesignScopeRepository._actor(session, request.project_id, actor_id)
            prior = self._committed(session, request, actor_id, invocation_id)
            self._canonical(session, request, invocation_id, actor_id, historical=prior is not None)
            self._parent(session, request)
            require_access()
            return prior

    def record(self, request, archive, ref, metadata, *, require_access):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            TestDesignScopeRepository._actor(session, request.project_id, metadata["actor_id"])
            prior = self._committed(session, request, metadata["actor_id"], metadata["invocation_id"])
            command = self._canonical(session, request, metadata["invocation_id"], metadata["actor_id"], historical=prior is not None)
            if prior is not None:
                if prior != metadata:
                    raise RunPlanObservationInvalid("observation replay cannot replace committed content")
                require_access()
                return prior
            expected = observation_record_metadata(archive, request.model_dump(mode="json"),
                **{key: metadata[key] for key in ("record_id", "invocation_id", "actor_id", "recorded_at")})
            if expected != metadata:
                raise RunPlanObservationInvalid("observation metadata differs from the complete verified archive")
            parent = self._parent(session, request)
            if any(metadata[key] != parent[key] for key in ("image_revision_id", "manifest_id")):
                raise RunPlanObservationInvalid("observation original source image registration differs")
            require_access()
            fields = {column.name for column in Record.__table__.columns} - {"artifact_ref", "payload", "content_hash"}
            row = Record(**{key: metadata[key] for key in fields}, artifact_ref=ref,
                payload=metadata, content_hash=acceptance_digest(metadata))
            session.add(row)
            session.flush()
            fields = {column.name for column in Member.__table__.columns} - {"payload", "content_hash"}
            for member in metadata["members"]:
                session.add(Member(**{key: member[key] for key in fields}, payload=member, content_hash=acceptance_digest(member)))
            session.flush()
            self._verify(session, row)
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=row.recorded_at, actor=row.actor_id, actor_kind="user",
                action=EVENT_TYPE, entity_type="run_plan_observations", entity_id=row.record_id, status="recorded",
                summary="Original response observations recorded; no execution consent or verified business coverage.",
                conversation_id=command.conversation_id, tool_invocation_id=command.id,
                object_refs=["run_plan_observations:" + row.record_id], evidence_refs=[],
                event_metadata={"run_plan_id": request.run_plan_id, "execution_authorized": False}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=EVENT_TYPE, occurred_at=row.recorded_at,
                correlation_id=request.project_id, entity_type="run_plan_observations", entity_id=row.record_id,
                conversation_id=command.conversation_id, agent_goal_id=command.input_payload.get("agent_goal_id"),
                entity_version=0, mutation_kind="append", patch={key: metadata[key] for key in EVENT_FIELDS},
                query_keys=[["run-plan-observations", request.project_id]], snapshot_hint=True), session=session)
            session.flush()
            return metadata

    def read(self, project_id, record_id):
        with session_scope() as session:
            row = session.get(Record, record_id)
            if row is None or row.project_id != project_id:
                raise KeyError("original observations not found")
            metadata = self._verify(session, row)
            request = self._request(session.get(ToolInvocationRecord, row.invocation_id))
            return {"metadata": metadata, "artifact_ref": row.artifact_ref, "request": request.model_dump(mode="json")}

    @classmethod
    def verify_event(cls, session, event):
        if event.event_type != EVENT_TYPE:
            return
        row = session.get(Record, event.entity_id)
        value = cls._verify(session, row)
        from .run_plan_event_integrity import verify_run_plan_event_envelope
        verify_run_plan_event_envelope(session, event, row, entity_type="run_plan_observations",
            query_key="run-plan-observations", error=RunPlanObservationInvalid)
        if (event.correlation_id != row.project_id or event.entity_type != "run_plan_observations"
                or event.patch != {key: value[key] for key in EVENT_FIELDS}):
            raise RunPlanObservationInvalid("observation event differs from its original fact")
