"""Append-only review/head CAS, canonical consent, audit and Outbox in one TX."""
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.quality_loop.automation_script_review_inputs import ScriptReviewRequest
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.automation_script_review import (
    SCRIPT_REVIEW_SCHEMA, SCRIPT_REVIEW_TOOL, ScriptReviewChanged, ScriptReviewIntegrityError,
)
from ...domain.system_image.source_access import SourceAccessDenied
from .automation_script_review_models import AutomationScriptReviewRecord as Record
from .automation_script_models import AutomationScriptRevisionRecord
from .automation_provenance_v1 import AutomationProvenanceProjectorV1
from .db_models import AuditEventRecord, ToolInvocationRecord
from .event_outbox_repository import EventOutboxRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .test_design_result_repository import TestDesignResultRepository
from .unit_of_work import session_scope


class AutomationScriptReviewRepository:
    @staticmethod
    def _value(row):
        value = row.payload
        if (not isinstance(value, dict) or acceptance_digest(value) != row.content_hash or any(value.get(key) != getattr(row, key)
                for key in ("project_id", "script_revision_id", "revision_id", "previous_revision_id",
                    "sequence", "status", "invocation_id"))):
            raise ScriptReviewIntegrityError("stored script review metadata mismatch")
        return value

    @staticmethod
    def _request(command):
        try:
            return ScriptReviewRequest.model_validate({key: value for key, value in query_payload(command.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}})
        except (ValidationError, TypeError, AttributeError):
            raise ScriptReviewIntegrityError("canonical script review request invalid") from None

    @classmethod
    def _canonical(cls, session, request, invocation_id, actor_id, *, historical=False):
        query = select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
        # A nested archive check must not wait on old commands locked by its caller.
        if not historical:
            query = query.with_for_update()
        command = session.scalar(query)
        if (command is None or command.tool_id != SCRIPT_REVIEW_TOOL
                or command.status not in ({"running", "completed", "failed"} if historical else {"running", "completed"})
                or command.input_payload.get("confirmed_by_user") is not True
                or command.input_payload.get("confirmed_actor_id") != actor_id or cls._request(command) != request):
            raise ScriptReviewIntegrityError("script review requires its exact confirmed canonical actor and request")
        TestDesignResultRepository._project_scope(session, command, request.project_id)
        draft = session.get(AutomationScriptRevisionRecord, request.script_revision_id)
        if draft is None or draft.project_id != request.project_id or draft.artifact_hash != request.script_artifact_hash:
            raise ScriptReviewIntegrityError("script review canonical draft pin mismatch")
        return command

    @classmethod
    def _rows(cls, session, project_id, script_revision_id):
        rows = session.scalars(select(Record).where(Record.project_id == project_id,
            Record.script_revision_id == script_revision_id).order_by(Record.sequence).limit(1001)).all()
        if len(rows) > 1000:
            raise ScriptReviewIntegrityError("script review history exceeds its explicit budget")
        if rows:
            AutomationProvenanceProjectorV1().reviews(session, session.get(AutomationScriptRevisionRecord, script_revision_id), rows)
        values = []
        for index, row in enumerate(rows):
            value = cls._value(row)
            if (value["sequence"] != index + 1
                    or value["previous_revision_id"] != (values[-1]["revision"]["revision_id"] if values else None)
                    or value["status"] not in {"reviewed", "withdrawn"}
                    or value["status"] == "withdrawn" and (not values or values[-1]["revision"]["status"] != "reviewed")):
                raise ScriptReviewIntegrityError("script review predecessor chain is incomplete")
            command = session.get(ToolInvocationRecord, value["invocation_id"])
            request = cls._request(command)
            cls._canonical(session, request, value["invocation_id"], value["authority_actor"], historical=True)
            if (request.project_id != project_id or request.script_revision_id != script_revision_id
                    or request.script_artifact_hash != value["script_artifact_hash"]
                    or request.expected_previous_revision_id != value["previous_revision_id"]
                    or acceptance_digest(request.model_dump(mode="json")) != value["request_hash"]):
                raise ScriptReviewIntegrityError("script review history canonical provenance mismatch")
            values.append({"revision": value, "artifact_ref": row.artifact_ref})
        return values

    def history(self, project_id, script_revision_id):
        with session_scope() as session:
            return self._rows(session, project_id, script_revision_id)

    def revision(self, project_id, revision_id):
        with session_scope() as session:
            row = session.get(Record, revision_id)
            if row is None or row.project_id != project_id:
                raise KeyError("script review revision not found")
            self._rows(session, project_id, row.script_revision_id)
            return self._value(row)

    @staticmethod
    def _actor(session, project_id, actor_id):
        try:
            TestDesignScopeRepository._actor(session, project_id, actor_id)
        except PermissionError:
            raise SourceAccessDenied("script review requires a current active reviewer") from None

    @classmethod
    def _committed(cls, session, request, actor_id, invocation_id):
        row = session.scalar(select(Record).where(Record.invocation_id == invocation_id))
        if row is None:
            return None
        cls._rows(session, request.project_id, request.script_revision_id)
        value = cls._value(row)
        if (value["project_id"] != request.project_id or value["script_revision_id"] != request.script_revision_id
                or value["authority_actor"] != actor_id
                or value["request_hash"] != acceptance_digest(request.model_dump(mode="json"))):
            raise ScriptReviewIntegrityError("script review invocation cannot be rebound")
        return value

    def committed(self, request, *, actor_id, invocation_id, require_access):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            self._actor(session, request.project_id, actor_id)
            prior = self._committed(session, request, actor_id, invocation_id)
            self._canonical(session, request, invocation_id, actor_id, historical=prior is not None)
            require_access()
            return prior

    def record(self, request, payload, ref, digest, *, require_current):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            actor_id = payload["authority_actor"]
            self._actor(session, request.project_id, actor_id)
            prior = self._committed(session, request, actor_id, payload["invocation_id"])
            command = self._canonical(session, request, payload["invocation_id"], actor_id, historical=prior is not None)
            if prior is not None:
                require_current()
                return prior
            try:
                confirmed = datetime.fromisoformat(str(command.input_payload.get("confirmed_at", "")))
                fresh = confirmed.tzinfo is not None and 0 <= (datetime.now(timezone.utc) - confirmed).total_seconds() <= 900
            except ValueError:
                fresh = False
            if (command.status != "running" or not fresh or payload.get("schema") != SCRIPT_REVIEW_SCHEMA
                    or payload.get("project_id") != request.project_id or payload["request"] != request.model_dump(mode="json")
                    or acceptance_digest(payload) != digest):
                raise ScriptReviewIntegrityError("script review requires fresh confirmation and exact archive")
            history = self._rows(session, request.project_id, request.script_revision_id)
            if (history[-1]["revision"]["revision_id"] if history else None) != request.expected_previous_revision_id:
                raise ScriptReviewChanged("script review head changed; reload before confirming")
            if len(history) == 1000:
                raise ScriptReviewIntegrityError("script review history exceeds its explicit budget")
            if request.decision == "withdraw" and (not history or history[-1]["revision"]["status"] != "reviewed"):
                raise ScriptReviewChanged("only a reviewed script head can be withdrawn")
            require_current()
            metadata = {"revision_id": str(uuid4()), "project_id": request.project_id,
                "script_revision_id": request.script_revision_id, "script_artifact_hash": request.script_artifact_hash,
                "previous_revision_id": request.expected_previous_revision_id, "sequence": len(history) + 1,
                "status": "reviewed" if request.decision == "review" else "withdrawn", "artifact_hash": digest,
                "request_hash": acceptance_digest(request.model_dump(mode="json")),
                **{key: payload[key] for key in ("authority_actor", "invocation_id", "recorded_at")}}
            review = Record(**{key: metadata[key] for key in ("revision_id", "project_id", "script_revision_id",
                "previous_revision_id", "sequence", "status", "invocation_id")}, artifact_ref=ref,
                payload=metadata, content_hash=acceptance_digest(metadata))
            session.add(review)
            AutomationProvenanceProjectorV1().record_review(session, review)
            event = "quality.automation.script_reviewed"
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=payload["recorded_at"], actor=actor_id, actor_kind="user",
                action=event, entity_type="automation_script_review", entity_id=metadata["revision_id"], status=metadata["status"],
                summary="Independent DSL/oracle review; no target execution or business pass claimed.",
                conversation_id=command.conversation_id, tool_invocation_id=command.id,
                object_refs=["automation_script_review:" + metadata["revision_id"]], evidence_refs=[],
                event_metadata={"script_revision_id": request.script_revision_id, "review_status": metadata["status"]}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=event,
                occurred_at=payload["recorded_at"], correlation_id=request.project_id,
                entity_type="automation_script_review", entity_id=metadata["revision_id"], conversation_id=command.conversation_id,
                agent_goal_id=command.input_payload.get("agent_goal_id"), entity_version=metadata["sequence"], mutation_kind="append",
                patch={key: metadata[key] for key in ("project_id", "script_revision_id", "revision_id", "status")},
                query_keys=[["automation-script-reviews", request.project_id, request.script_revision_id]], snapshot_hint=True), session=session)
            session.flush()
            return metadata
