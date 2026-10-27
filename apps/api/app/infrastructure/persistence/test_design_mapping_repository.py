from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.quality_loop.test_design_mapping_inputs import MappingReviewInput
from ...application.quality_loop.mapping_finalization_inputs import MappingFinalizeInput
from ...application.quality_loop.test_design_mapping_pins import mapping_review_query_keys
from ...domain.quality_loop.mapping_part_sets import FINALIZE_TOOL, PARTITIONED_MAPPING_SCHEMA
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.test_design_mapping import MAPPING_TOOL, TestDesignMappingChanged, TestDesignMappingIntegrityError
from .db_models import ToolInvocationRecord, AuditEventRecord
from .test_design_mapping_models import TestDesignMappingRecord as Record
from .test_design_scope_repository import TestDesignScopeRepository
from .test_design_result_repository import TestDesignResultRepository
from .event_outbox_repository import EventOutboxRepository
from .unit_of_work import session_scope


class TestDesignMappingRepository:
    __test__ = False

    @staticmethod
    def _value(row):
        value = row.payload
        if (acceptance_digest(value) != row.content_hash or any(value.get(key) != getattr(row, key)
                for key in ("revision_id", "generation_id", "project_id", "previous_revision_id", "sequence", "status", "invocation_id"))):
            raise TestDesignMappingIntegrityError("stored mapping metadata mismatch")
        return value

    @classmethod
    def _history(cls, session, project_id, generation_id, through_revision_id=None):
        query = select(Record).where(Record.project_id == project_id, Record.generation_id == generation_id)
        if through_revision_id is not None:
            row = session.get(Record, through_revision_id)
            if row is None or (row.project_id, row.generation_id) != (project_id, generation_id):
                raise KeyError("mapping revision not found")
            query = query.where(Record.sequence <= row.sequence)
        values = [cls._value(row) for row in session.scalars(query.order_by(Record.sequence).limit(1001))]
        if len(values) > 1000:
            raise TestDesignMappingIntegrityError("mapping history exceeds supported budget")
        for index, value in enumerate(values):
            if (value["sequence"] != index + 1
                    or value["previous_revision_id"] != (values[index - 1]["revision_id"] if index else None)
                    or value["status"] not in {"reviewed", "withdrawn"}
                    or value["status"] == "withdrawn" and (index == 0 or values[index - 1]["status"] != "reviewed")):
                raise TestDesignMappingIntegrityError("mapping history is incomplete")
        return values

    def history(self, project_id, generation_id, through_revision_id=None):
        with session_scope() as session:
            return self._history(session, project_id, generation_id, through_revision_id)

    @staticmethod
    def _request(row):
        try:
            input_type = MappingFinalizeInput if row.tool_id == FINALIZE_TOOL else MappingReviewInput
            return input_type.model_validate({key: value for key, value in query_payload(row.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}})
        except (ValidationError, TypeError, AttributeError) as exc:
            raise TestDesignMappingIntegrityError("canonical mapping request invalid") from exc

    @classmethod
    def _canonical(cls, session, request, invocation_id, actor_id, *, historical=False, lock=True):
        query = select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).execution_options(populate_existing=True)
        if lock:
            query = query.with_for_update()
        command = session.scalar(query)
        allowed = {"running", "completed", "failed"} if historical else {"running", "completed"}
        tool_id = FINALIZE_TOOL if isinstance(request, MappingFinalizeInput) else MAPPING_TOOL
        if (command is None or command.tool_id != tool_id or command.status not in allowed
                or command.input_payload.get("confirmed_by_user") is not True
                or command.input_payload.get("confirmed_actor_id") != actor_id or cls._request(command) != request):
            raise TestDesignMappingIntegrityError("mapping requires its exact canonical confirmed actor and request")
        TestDesignResultRepository._project_scope(session, command, request.project_id)
        return command

    def get(self, project_id, revision_id):
        with session_scope() as session:
            row = session.get(Record, revision_id)
            if row is None or row.project_id != project_id:
                raise KeyError("mapping revision not found")
            value = self._history(session, project_id, row.generation_id, revision_id)[-1]
            command = session.get(ToolInvocationRecord, value["invocation_id"])
            if command is None:
                raise TestDesignMappingIntegrityError("mapping command unavailable")
            request = self._request(command)
            self._canonical(session, request, value["invocation_id"], value["authority_actor"], historical=True, lock=False)
            if (acceptance_digest(request.model_dump(mode="json")) != value["request_hash"]
                    or request.project_id != project_id or request.generation_id != row.generation_id
                    or request.generation_artifact_hash != value["generation_artifact_hash"]
                    or request.expected_previous_revision_id != row.previous_revision_id):
                raise TestDesignMappingIntegrityError("mapping canonical provenance mismatch")
            partitioned = isinstance(request, MappingFinalizeInput)
            if ((value.get("mapping_schema") == PARTITIONED_MAPPING_SCHEMA) != partitioned
                    or partitioned and (value.get("part_set_digest") != request.part_set_digest or value.get("plan_digest") != request.plan_digest)):
                raise TestDesignMappingIntegrityError("mapping canonical schema or complete set mismatch")
            return value, row.artifact_ref

    @classmethod
    def _committed(cls, session, request, actor_id, invocation_id):
        row = session.scalar(select(Record).where(Record.invocation_id == invocation_id))
        if row is None:
            return None
        value = cls._value(row)
        if (row.project_id != request.project_id or row.generation_id != request.generation_id
                or value["authority_actor"] != actor_id or value["request_hash"] != acceptance_digest(request.model_dump(mode="json"))):
            raise TestDesignMappingIntegrityError("mapping invocation already bound")
        return value

    def committed(self, request, *, actor_id, invocation_id, require_access):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            TestDesignScopeRepository._actor(session, request.project_id, actor_id)
            value = self._committed(session, request, actor_id, invocation_id)
            self._canonical(session, request, invocation_id, actor_id, historical=value is not None)
            require_access()
            return value

    def record(self, request, payload, artifact_ref, artifact_hash, *, require_current):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            TestDesignScopeRepository._actor(session, request.project_id, payload["authority_actor"])
            prior = self._committed(session, request, payload["authority_actor"], payload["invocation_id"])
            command = self._canonical(session, request, payload["invocation_id"], payload["authority_actor"], historical=prior is not None)
            if prior is not None:
                require_current()
                return prior
            try:
                confirmed = datetime.fromisoformat(str(command.input_payload.get("confirmed_at", "")))
                fresh = confirmed.tzinfo is not None and 0 <= (datetime.now(timezone.utc) - confirmed).total_seconds() <= 900
            except ValueError:
                fresh = False
            if (command.status != "running" or not fresh or acceptance_digest(payload) != artifact_hash
                    or payload["request"] != request.model_dump(mode="json")
                    or payload.get("schema") != (PARTITIONED_MAPPING_SCHEMA if isinstance(request, MappingFinalizeInput) else
                        "nasus.test-design-mapping-review.v1")):
                raise TestDesignMappingIntegrityError("mapping commit requires fresh confirmation and exact payload")
            history = self._history(session, request.project_id, request.generation_id)
            if (history[-1]["revision_id"] if history else None) != request.expected_previous_revision_id:
                raise TestDesignMappingChanged("mapping head changed; reload before reviewing")
            if len(history) == 1000:
                raise TestDesignMappingIntegrityError("mapping history exceeds supported budget")
            if request.decision == "withdraw" and (not history or history[-1]["status"] != "reviewed"):
                raise TestDesignMappingChanged("only a reviewed mapping can be withdrawn")
            require_current()
            value = {"revision_id": str(uuid4()), "project_id": request.project_id, "generation_id": request.generation_id,
                "generation_artifact_hash": request.generation_artifact_hash,
                "previous_revision_id": request.expected_previous_revision_id, "sequence": len(history) + 1,
                "status": "reviewed" if request.decision == "review" else "withdrawn", "artifact_hash": artifact_hash,
                "request_hash": acceptance_digest(request.model_dump(mode="json")),
                **{key: payload[key] for key in ("authority_actor", "invocation_id", "recorded_at")}}
            if isinstance(request, MappingFinalizeInput):
                value.update(mapping_schema=PARTITIONED_MAPPING_SCHEMA, plan_digest=request.plan_digest, part_set_digest=request.part_set_digest)
            session.add(Record(**{key: value[key] for key in ("revision_id", "project_id", "generation_id", "previous_revision_id",
                "sequence", "status", "invocation_id")}, artifact_ref=artifact_ref, payload=value, content_hash=acceptance_digest(value)))
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=payload["recorded_at"], actor=payload["authority_actor"], actor_kind="user",
                action="quality.test_design_mapping.reviewed", entity_type="test_design_mapping", entity_id=value["revision_id"], status="completed",
                summary="Independent assertion mapping reviewed; no target execution or pass claimed.",
                conversation_id=command.conversation_id, tool_invocation_id=command.id, agent_goal_id=command.input_payload.get("agent_goal_id"),
                object_refs=["test_design_mapping:" + value["revision_id"]], evidence_refs=[],
                event_metadata={"generation_id": request.generation_id, "mapping_status": value["status"]}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="quality.test_design_mapping.reviewed",
                occurred_at=payload["recorded_at"], correlation_id=request.project_id, entity_type="test_design_mapping", entity_id=value["revision_id"],
                conversation_id=command.conversation_id, agent_goal_id=command.input_payload.get("agent_goal_id"),
                entity_version=value["sequence"], mutation_kind="append",
                patch={key: value[key] for key in ("project_id", "generation_id", "revision_id", "status")},
                query_keys=mapping_review_query_keys(request.project_id), snapshot_hint=True), session=session)
            session.flush()
            return value
