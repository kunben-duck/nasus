from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select, func

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.quality_loop.mapping_part_inputs import MappingPartStageInput, STAGE_PART_TOOL, STAGED_PART_SCHEMA
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.test_design_mapping import TestDesignMappingChanged, TestDesignMappingIntegrityError
from ...domain.quality_loop.mapping_partitions import MAX_PARTS
from .db_models import ToolInvocationRecord, AuditEventRecord
from .mapping_part_models import MappingPartRevisionRecord as Record
from .test_design_scope_repository import TestDesignScopeRepository
from .test_design_result_repository import TestDesignResultRepository
from .test_design_mapping_repository import TestDesignMappingRepository
from .event_outbox_repository import EventOutboxRepository
from .unit_of_work import session_scope


class MappingPartRepository:
    def heads(self, project_id, generation_id, plan_digest, actor_id):
        with session_scope() as session:
            ranked = select(Record.part_revision_id, func.row_number().over(partition_by=Record.sequence,
                order_by=Record.revision_sequence.desc()).label("position")).where(
                    Record.project_id == project_id, Record.generation_id == generation_id,
                    Record.plan_digest == plan_digest, Record.authority_actor == actor_id).subquery()
            rows = session.scalars(select(Record).join(ranked, Record.part_revision_id == ranked.c.part_revision_id)
                .where(ranked.c.position == 1).order_by(Record.sequence).limit(MAX_PARTS + 1)).all()
            if len(rows) > MAX_PARTS:
                raise TestDesignMappingIntegrityError("mapping set exceeds the complete plan budget")
            return [self._value(row) for row in rows]

    @staticmethod
    def _value(row):
        value = row.payload
        if (acceptance_digest(value) != row.content_hash or any(value.get(key) != getattr(row, key) for key in (
                "part_revision_id", "project_id", "generation_id", "plan_digest", "sequence", "authority_actor",
                "revision_sequence", "expected_previous_revision_id", "expected_previous_part_revision_id", "invocation_id"))
                or value.get("assertion_mapped") is not False or value.get("execution_authorized") is not False):
            raise TestDesignMappingIntegrityError("stored mapping part metadata mismatch")
        return value

    @classmethod
    def _history(cls, session, project_id, generation_id, plan_digest, sequence, actor_id, through_revision_id=None):
        query = select(Record).where(Record.project_id == project_id, Record.generation_id == generation_id,
            Record.plan_digest == plan_digest, Record.sequence == sequence, Record.authority_actor == actor_id)
        if through_revision_id is not None:
            row = session.get(Record, through_revision_id)
            if row is None or (row.project_id, row.generation_id, row.plan_digest, row.sequence, row.authority_actor) != (
                    project_id, generation_id, plan_digest, sequence, actor_id):
                raise KeyError("staged mapping part not found")
            query = query.where(Record.revision_sequence <= row.revision_sequence)
        values = [cls._value(row) for row in session.scalars(query.order_by(Record.revision_sequence).limit(1001))]
        if len(values) > 1000:
            raise TestDesignMappingIntegrityError("mapping part history exceeds its revision budget")
        for index, value in enumerate(values):
            if (value["revision_sequence"] != index + 1 or value["expected_previous_part_revision_id"] != (
                    values[index - 1]["part_revision_id"] if index else None)):
                raise TestDesignMappingIntegrityError("mapping part history is incomplete")
        return values

    def history(self, project_id, generation_id, plan_digest, sequence, actor_id, through_revision_id=None):
        with session_scope() as session:
            return self._history(session, project_id, generation_id, plan_digest, sequence, actor_id, through_revision_id)

    @staticmethod
    def _request(command):
        try:
            return MappingPartStageInput.model_validate({key: value for key, value in query_payload(command.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}})
        except (ValidationError, TypeError, AttributeError) as exc:
            raise TestDesignMappingIntegrityError("canonical mapping part request invalid") from exc

    @classmethod
    def _canonical(cls, session, request, invocation_id, actor_id, *, historical=False, lock=True):
        query = select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).execution_options(populate_existing=True)
        if lock:
            query = query.with_for_update()
        command = session.scalar(query)
        statuses = {"running", "completed", "failed"} if historical else {"running", "completed"}
        if (command is None or command.tool_id != STAGE_PART_TOOL or command.status not in statuses
                or command.input_payload.get("confirmed_by_user") is not True
                or command.input_payload.get("confirmed_actor_id") != actor_id or cls._request(command) != request):
            raise TestDesignMappingIntegrityError("mapping part requires exact canonical confirmation, actor and request")
        TestDesignResultRepository._project_scope(session, command, request.project_id)
        return command

    def get(self, project_id, revision_id):
        with session_scope() as session:
            row = session.get(Record, revision_id)
            if row is None or row.project_id != project_id:
                raise KeyError("staged mapping part not found")
            value = self._history(session, row.project_id, row.generation_id, row.plan_digest, row.sequence,
                row.authority_actor, revision_id)[-1]
            command = session.get(ToolInvocationRecord, value["invocation_id"])
            if command is None:
                raise TestDesignMappingIntegrityError("staged mapping part command unavailable")
            request = self._request(command)
            self._canonical(session, request, command.id, value["authority_actor"], historical=True, lock=False)
            if (value["request_hash"] != acceptance_digest(request.model_dump(mode="json"))
                    or any(getattr(request, key) != value[key] for key in (
                        "project_id", "generation_id", "generation_artifact_hash", "plan_digest", "sequence", "part_digest",
                        "expected_previous_revision_id", "expected_previous_part_revision_id"))):
                raise TestDesignMappingIntegrityError("staged mapping part canonical provenance mismatch")
            return value, row.artifact_ref

    @classmethod
    def _committed(cls, session, request, actor_id, invocation_id):
        row = session.scalar(select(Record).where(Record.invocation_id == invocation_id))
        if row is None:
            return None
        value = cls._value(row)
        if (row.project_id != request.project_id or row.generation_id != request.generation_id
                or value["authority_actor"] != actor_id or value["request_hash"] != acceptance_digest(request.model_dump(mode="json"))):
            raise TestDesignMappingIntegrityError("staged mapping part invocation already bound")
        return value

    def committed(self, request, *, actor_id, invocation_id, require_access):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            TestDesignScopeRepository._actor(session, request.project_id, actor_id)
            value = self._committed(session, request, actor_id, invocation_id)
            # A lost terminal acknowledgement must not hide an already committed part.
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
                    or payload.get("schema") != STAGED_PART_SCHEMA or payload["request"] != request.model_dump(mode="json")
                    or payload.get("assertion_mapped") is not False or payload.get("execution_authorized") is not False):
                raise TestDesignMappingIntegrityError("mapping part commit requires fresh confirmation and exact payload")
            reviews = TestDesignMappingRepository._history(session, request.project_id, request.generation_id)
            if (reviews[-1]["revision_id"] if reviews else None) != request.expected_previous_revision_id:
                raise TestDesignMappingChanged("mapping head changed before staging")
            history = self._history(session, request.project_id, request.generation_id, request.plan_digest,
                request.sequence, payload["authority_actor"])
            if (history[-1]["part_revision_id"] if history else None) != request.expected_previous_part_revision_id:
                raise TestDesignMappingChanged("mapping part was edited; reload its head")
            if len(history) == 1000:
                raise TestDesignMappingIntegrityError("mapping part history exceeds its revision budget")
            require_current()
            value = {"part_revision_id": str(uuid4()), **{key: getattr(request, key) for key in (
                "project_id", "generation_id", "generation_artifact_hash", "plan_digest", "sequence", "part_digest",
                "expected_previous_revision_id", "expected_previous_part_revision_id")}, "revision_sequence": len(history) + 1,
                "artifact_hash": artifact_hash, "request_hash": acceptance_digest(request.model_dump(mode="json")),
                **{key: payload[key] for key in ("authority_actor", "invocation_id", "recorded_at")},
                "assertion_mapped": False, "execution_authorized": False}
            session.add(Record(**{key: value[key] for key in (
                "part_revision_id", "project_id", "generation_id", "plan_digest", "sequence", "authority_actor",
                "revision_sequence", "expected_previous_revision_id", "expected_previous_part_revision_id", "invocation_id")},
                artifact_ref=artifact_ref, payload=value, content_hash=acceptance_digest(value)))
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=payload["recorded_at"], actor=payload["authority_actor"],
                actor_kind="user", action="quality.test_design_mapping.part_staged", entity_type="test_design_mapping_part",
                entity_id=value["part_revision_id"], status="completed", summary="Private review part saved; no final mapping or execution granted.",
                conversation_id=command.conversation_id, tool_invocation_id=command.id, agent_goal_id=command.input_payload.get("agent_goal_id"),
                object_refs=["test_design_mapping_part:" + value["part_revision_id"]], evidence_refs=[],
                event_metadata={"generation_id": request.generation_id, "sequence": request.sequence, "assertion_mapped": False}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="quality.test_design_mapping.part_staged",
                occurred_at=payload["recorded_at"], correlation_id=request.project_id, entity_type="test_design_mapping_part",
                entity_id=value["part_revision_id"], conversation_id=command.conversation_id,
                agent_goal_id=command.input_payload.get("agent_goal_id"), entity_version=value["revision_sequence"], mutation_kind="append",
                patch={key: value[key] for key in ("project_id", "generation_id", "part_revision_id", "sequence", "assertion_mapped")},
                query_keys=[["test-design-mapping-parts", request.project_id, request.generation_id]]), session=session)
            session.flush()
            return value
