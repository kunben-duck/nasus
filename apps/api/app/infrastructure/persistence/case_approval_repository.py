from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.quality_loop.case_approvals import CaseApprovalReviewInput
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.case_approval import (
    CASE_APPROVAL_SCHEMA, CASE_APPROVAL_TOOL, CASE_APPROVAL_EVENT,
    CaseApprovalChanged, CaseApprovalIntegrityError, case_approval_cohort,
)
from .case_approval_models import CaseApprovalRevisionRecord as Record, CaseApprovalMemberRecord as Member
from .db_models import ToolInvocationRecord, AuditEventRecord
from .event_outbox_repository import EventOutboxRepository
from .test_design_result_models import TestDesignCaseRecord
from .test_design_result_repository import TestDesignResultRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .unit_of_work import session_scope


class CaseApprovalRepository:
    @staticmethod
    def _request(command):
        try:
            return CaseApprovalReviewInput.model_validate({key: value for key, value in
                query_payload(command.input_payload).items() if key not in {"confirmed_at", "confirmed_by_user"}})
        except (ValueError, TypeError, AttributeError) as error:
            raise CaseApprovalIntegrityError("canonical case admission request is invalid") from error

    @classmethod
    def _canonical(cls, session, request, invocation_id, actor_id, *, historical=False, lock=True):
        query = select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).execution_options(populate_existing=True)
        if lock:
            query = query.with_for_update()
        command = session.scalar(query)
        allowed = {"running", "completed", "failed"} if historical else {"running", "completed"}
        if (command is None or command.tool_id != CASE_APPROVAL_TOOL or command.status not in allowed
                or command.input_payload.get("confirmed_by_user") is not True
                or command.input_payload.get("confirmed_actor_id") != actor_id or cls._request(command) != request):
            raise CaseApprovalIntegrityError("case admission requires its exact canonical confirmed actor and request")
        TestDesignResultRepository._project_scope(session, command, request.project_id)
        return command

    @staticmethod
    def _value(row):
        value = row.payload
        if (acceptance_digest(value) != row.content_hash or any(value.get(key) != getattr(row, key) for key in
                ("revision_id", "project_id", "generation_id", "mapping_revision_id", "cohort_id",
                 "previous_revision_id", "sequence", "status", "invocation_id"))):
            raise CaseApprovalIntegrityError("case admission metadata is inconsistent")
        return value

    @classmethod
    def _history(cls, session, project_id, cohort_id, through_revision_id=None):
        query = select(Record).where(Record.project_id == project_id, Record.cohort_id == cohort_id)
        if through_revision_id is not None:
            end = session.get(Record, through_revision_id)
            if end is None or (end.project_id, end.cohort_id) != (project_id, cohort_id):
                raise KeyError("case admission revision not found")
            query = query.where(Record.sequence <= end.sequence)
        rows = list(session.scalars(query.order_by(Record.sequence).limit(1001)))
        if len(rows) > 1000:
            raise CaseApprovalIntegrityError("case admission history exceeds its complete-read budget")
        values = []
        for index, row in enumerate(rows):
            value = cls._value(row)
            if (value["sequence"] != index + 1 or value["previous_revision_id"] !=
                    (values[-1]["revision_id"] if values else None)
                    or value["status"] not in {"approved", "withdrawn"}
                    or value["status"] == "withdrawn" and (not values or values[-1]["status"] != "approved")):
                raise CaseApprovalIntegrityError("case admission history is incomplete")
            command = session.get(ToolInvocationRecord, row.invocation_id)
            request = cls._request(command)
            cls._canonical(session, request, row.invocation_id, value["authority_actor"], historical=True, lock=False)
            members = list(session.scalars(select(Member).where(Member.revision_id == row.revision_id).order_by(Member.case_id)))
            pins = [{"case_id": item.case_id, "case_digest": item.case_digest} for item in members]
            identity = case_approval_cohort({"project_id": project_id,
                "generation_pin": {"generation_id": row.generation_id}, "case_pins": pins})
            if (not members or len(members) != value["case_count"] or identity != cohort_id
                    or any((item.project_id, item.generation_id) != (project_id, row.generation_id) for item in members)
                    or request.project_id != project_id or request.mapping_revision_id != row.mapping_revision_id
                    or value["status"] != ("approved" if request.decision == "approve" else "withdrawn")
                    or sorted(request.case_ids) != [item.case_id for item in members]
                    or request.expected_previous_revision_id != row.previous_revision_id
                    or request.expected_input_digest != value["input_digest"]
                    or acceptance_digest(request.model_dump(mode="json")) != value["request_hash"]):
                raise CaseApprovalIntegrityError("case admission members or canonical request changed")
            for item in members:
                source = session.get(TestDesignCaseRecord, (row.generation_id, item.case_id))
                if (source is None or source.project_id != project_id or source.content_hash != item.case_digest
                        or acceptance_digest(source.payload) != item.case_digest):
                    raise CaseApprovalIntegrityError("case admission no longer matches its original case revision")
            values.append(value)
        return values

    def history(self, project_id, cohort_id, through_revision_id=None):
        with session_scope() as session:
            return self._history(session, project_id, cohort_id, through_revision_id)

    def archives(self, project_id, cohort_id):
        with session_scope() as session:
            values = self._history(session, project_id, cohort_id)
            rows = session.scalars(select(Record).where(Record.project_id == project_id, Record.cohort_id == cohort_id))
            refs = {row.revision_id: row.artifact_ref for row in rows}
            return [(value, refs[value["revision_id"]]) for value in values]

    def get(self, project_id, revision_id):
        with session_scope() as session:
            row = session.get(Record, revision_id)
            if row is None or row.project_id != project_id:
                raise KeyError("case admission revision not found")
            return self._history(session, project_id, row.cohort_id, revision_id)[-1], row.artifact_ref

    @classmethod
    def _committed(cls, session, request, basis, actor_id, invocation_id):
        row = session.scalar(select(Record).where(Record.invocation_id == invocation_id))
        if row is None:
            return None
        value = cls._history(session, request.project_id, row.cohort_id, row.revision_id)[-1]
        if (row.project_id != request.project_id or row.cohort_id != case_approval_cohort(basis)
                or value["authority_actor"] != actor_id or value["input_digest"] != basis["input_digest"]
                or value["request_hash"] != acceptance_digest(request.model_dump(mode="json"))):
            raise CaseApprovalIntegrityError("case admission invocation is already bound to another input")
        return value

    def committed(self, request, basis, *, actor_id, invocation_id, require_access):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            TestDesignScopeRepository._actor(session, request.project_id, actor_id)
            value = self._committed(session, request, basis, actor_id, invocation_id)
            self._canonical(session, request, invocation_id, actor_id, historical=value is not None)
            require_access()
            return value

    def record(self, request, payload, ref, digest, *, require_current):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            actor, invocation = payload["authority_actor"], payload["invocation_id"]
            TestDesignScopeRepository._actor(session, request.project_id, actor)
            basis = payload["basis"]
            prior = self._committed(session, request, basis, actor, invocation)
            command = self._canonical(session, request, invocation, actor, historical=prior is not None)
            if prior is not None:
                require_current()
                return prior
            now = session.scalar(select(func.clock_timestamp()))
            try:
                confirmed = datetime.fromisoformat(str(command.input_payload.get("confirmed_at", "")))
                fresh = confirmed.tzinfo is not None and 0 <= (now - confirmed).total_seconds() <= 900
            except ValueError:
                fresh = False
            cohort = case_approval_cohort(basis)
            if (not fresh or command.status != "running" or payload["schema"] != CASE_APPROVAL_SCHEMA
                    or acceptance_digest(payload) != digest or payload["request"] != request.model_dump(mode="json")
                    or payload["cohort_id"] != cohort or basis["project_id"] != request.project_id
                    or basis["input_digest"] != request.expected_input_digest):
                raise CaseApprovalIntegrityError("case admission needs fresh PostgreSQL-time confirmation and exact input")
            history = self._history(session, request.project_id, cohort)
            if (history[-1]["revision_id"] if history else None) != request.expected_previous_revision_id:
                raise CaseApprovalChanged("case admission head changed; inspect again")
            if len(history) == 1000 or request.decision == "withdraw" and (not history
                    or history[-1]["status"] != "approved" or history[-1]["input_digest"] != basis["input_digest"]):
                raise CaseApprovalChanged("only the current approved case cohort can be withdrawn")
            require_current()
            value = {"revision_id": str(uuid4()), "project_id": request.project_id,
                "generation_id": basis["generation_pin"]["generation_id"], "mapping_revision_id": request.mapping_revision_id,
                "cohort_id": cohort, "previous_revision_id": request.expected_previous_revision_id,
                "sequence": len(history) + 1, "status": "approved" if request.decision == "approve" else "withdrawn",
                "artifact_hash": digest, "request_hash": acceptance_digest(request.model_dump(mode="json")),
                "input_digest": basis["input_digest"], "case_count": len(basis["case_pins"]),
                **{key: payload[key] for key in ("authority_actor", "invocation_id", "recorded_at")}}
            session.add(Record(**{key: value[key] for key in ("revision_id", "project_id", "generation_id",
                "mapping_revision_id", "cohort_id", "previous_revision_id", "sequence", "status", "invocation_id")},
                artifact_ref=ref, payload=value, content_hash=acceptance_digest(value)))
            session.flush()
            for pin in basis["case_pins"]:
                source = session.get(TestDesignCaseRecord, (value["generation_id"], pin["case_id"]))
                if (source is None or source.project_id != request.project_id or source.content_hash != pin["case_digest"]
                        or acceptance_digest(source.payload) != pin["case_digest"]):
                    raise CaseApprovalIntegrityError("case admission cannot replace a persisted original case")
                session.add(Member(revision_id=value["revision_id"], project_id=request.project_id,
                    generation_id=value["generation_id"], **pin))
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=payload["recorded_at"], actor=actor, actor_kind="user",
                action=CASE_APPROVAL_EVENT, entity_type="test_design_case_approval", entity_id=value["revision_id"], status="completed",
                summary="Independent case admission recorded; no target execution or business coverage granted.",
                conversation_id=command.conversation_id, tool_invocation_id=command.id,
                agent_goal_id=command.input_payload.get("agent_goal_id"), object_refs=["test_design_case_approval:" + value["revision_id"]],
                evidence_refs=[], event_metadata={"generation_id": value["generation_id"], "admission_status": value["status"]}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=CASE_APPROVAL_EVENT,
                occurred_at=payload["recorded_at"], correlation_id=request.project_id, entity_type="test_design_case_approval",
                entity_id=value["revision_id"], conversation_id=command.conversation_id,
                agent_goal_id=command.input_payload.get("agent_goal_id"), entity_version=value["sequence"], mutation_kind="append",
                patch={key: value[key] for key in ("project_id", "revision_id", "status")},
                query_keys=[["test-design-case-approvals", request.project_id]], snapshot_hint=True), session=session)
            require_current()
            session.flush()
            return value
