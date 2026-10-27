from uuid import uuid4

from sqlalchemy import select, text

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.quality_loop.test_design_scope_inputs import ScopeReviewInput
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.test_design_scope import SCOPE_TOOL, TestDesignScopeChanged, TestDesignScopeIntegrityError, scope_identity
from .db_models import ToolInvocationRecord, ConversationRecord, AgentGoalRecord, AuditEventRecord, UserIdentityRecord, ProjectRoleBindingRecord
from .test_design_scope_models import TestDesignScopeRecord as Record
from .event_outbox_repository import EventOutboxRepository
from .source_snapshot_repository import SourceSnapshotRepository
from .unit_of_work import session_scope


class TestDesignScopeRepository:
    __test__ = False

    @staticmethod
    def _lock(session, project_id):
        SourceSnapshotRepository._lock(session, project_id)
        session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"nasus:source-access:{project_id}"})

    @staticmethod
    def _actor(session, project_id, actor_id):
        # A row lock alone does not refresh identities already held by this Session.
        identity = session.scalar(select(UserIdentityRecord).where(UserIdentityRecord.user_id == actor_id)
            .with_for_update().execution_options(populate_existing=True))
        if identity is None or identity.status != "active":
            raise PermissionError("scope requires an active registered reviewer")
        roles = session.scalars(select(ProjectRoleBindingRecord).where(ProjectRoleBindingRecord.project_id == project_id,
            ProjectRoleBindingRecord.user_id == actor_id, ProjectRoleBindingRecord.version_id.is_(None),
            ProjectRoleBindingRecord.session_id.is_(None), ProjectRoleBindingRecord.status == "active")
            .with_for_update().execution_options(populate_existing=True)).all()
        if identity.role != "platform_admin" and (len(roles) != 1 or roles[0].role not in {"qa_lead", "project_admin"}):
            raise PermissionError("scope reviewer membership changed")

    @staticmethod
    def _value(row):
        value = row.payload
        if (acceptance_digest(value) != row.content_hash
                or value.get("scope_id") != scope_identity(row.project_id, row.context_id)
                or any(value.get(k) != getattr(row, k) for k in ("revision_id", "scope_id", "project_id", "context_id",
                    "previous_revision_id", "sequence", "status", "invocation_id"))):
            raise TestDesignScopeIntegrityError("stored scope metadata mismatch")
        return value

    @classmethod
    def _history(cls, session, project_id, scope_id, through_revision_id=None):
        query = select(Record).where(Record.project_id == project_id, Record.scope_id == scope_id)
        if through_revision_id is not None:
            row = session.get(Record, through_revision_id)
            if row is None or (row.project_id, row.scope_id) != (project_id, scope_id):
                raise KeyError("scope revision not found")
            query = query.where(Record.sequence <= row.sequence)
        values = [cls._value(row) for row in session.scalars(query.order_by(Record.sequence).limit(1001))]
        if len(values) > 1000:
            raise TestDesignScopeIntegrityError("scope history exceeds supported budget")
        for i, value in enumerate(values):
            if (value["sequence"] != i + 1 or value["previous_revision_id"] != (values[i - 1]["revision_id"] if i else None)
                    or value["status"] not in {"approved", "withdrawn"}
                    or value["status"] == "withdrawn" and (i == 0 or values[i - 1]["status"] != "approved")):
                raise TestDesignScopeIntegrityError("scope history is incomplete")
        return values

    def history(self, project_id, scope_id, through_revision_id=None):
        with session_scope() as session:
            return self._history(session, project_id, scope_id, through_revision_id)

    def get(self, project_id, revision_id):
        with session_scope() as session:
            row = session.get(Record, revision_id)
            if row is None or row.project_id != project_id:
                raise KeyError("scope revision not found")
            history = self._history(session, project_id, row.scope_id, revision_id)
            return history[-1], row.artifact_ref

    @staticmethod
    def _canonical(session, request, invocation_id, actor_id):
        row = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
            .with_for_update().execution_options(populate_existing=True))
        if (row is None or row.tool_id != SCOPE_TOOL or row.status not in {"running", "completed"}
                or row.input_payload.get("confirmed_by_user") is not True
                or row.input_payload.get("confirmed_actor_id") != actor_id
                or ScopeReviewInput.model_validate({k: v for k, v in query_payload(row.input_payload).items()
                    if k not in {"confirmed_by_user", "confirmed_at"}}) != request):
            raise TestDesignScopeIntegrityError("scope requires its confirmed canonical actor and request")
        if row.conversation_id:
            conversation = session.get(ConversationRecord, row.conversation_id)
            if conversation is None or conversation.project_id != request.project_id:
                raise TestDesignScopeIntegrityError("scope conversation mismatch")
        if row.input_payload.get("agent_goal_id"):
            goal = session.get(AgentGoalRecord, row.input_payload["agent_goal_id"])
            if goal is None or goal.project_id != request.project_id or goal.conversation_id != row.conversation_id:
                raise TestDesignScopeIntegrityError("scope goal mismatch")
        return row

    @classmethod
    def _committed(cls, session, request, actor_id, invocation_id):
        row = session.scalar(select(Record).where(Record.invocation_id == invocation_id))
        if row is None:
            return None
        value = cls._value(row)
        if (row.project_id != request.project_id or value["authority_actor"] != actor_id
                or value["request_hash"] != acceptance_digest(request.model_dump(mode="json"))):
            raise TestDesignScopeIntegrityError("scope invocation was already bound")
        return value

    def committed(self, request, *, actor_id, invocation_id, require_access):
        with session_scope() as session:
            self._lock(session, request.project_id)
            self._actor(session, request.project_id, actor_id)
            self._canonical(session, request, invocation_id, actor_id)
            value = self._committed(session, request, actor_id, invocation_id)
            require_access()
            return value

    def record(self, request, payload, artifact_ref, artifact_hash, *, require_current):
        with session_scope() as session:
            self._lock(session, request.project_id)
            self._actor(session, request.project_id, payload["authority_actor"])
            command = self._canonical(session, request, payload["invocation_id"], payload["authority_actor"])
            prior = self._committed(session, request, payload["authority_actor"], payload["invocation_id"])
            if prior is not None:
                return prior
            if command.status != "running" or acceptance_digest(payload) != artifact_hash or payload["request"] != request.model_dump(mode="json"):
                raise TestDesignScopeIntegrityError("scope commit payload mismatch")
            ident = scope_identity(request.project_id, request.context_id)
            history = self._history(session, request.project_id, ident)
            if (history[-1]["revision_id"] if history else None) != request.expected_previous_revision_id:
                raise TestDesignScopeChanged("scope head changed; reload before reviewing")
            if request.decision == "withdraw" and (not history or history[-1]["status"] != "approved"):
                raise ValueError("only an approved scope can be withdrawn")
            require_current()
            value = {"revision_id": str(uuid4()), "scope_id": ident, "project_id": request.project_id,
                "context_id": request.context_id, "context_artifact_hash": request.context_artifact_hash,
                "previous_revision_id": request.expected_previous_revision_id, "sequence": len(history) + 1,
                "status": "approved" if request.decision == "approve" else "withdrawn", "artifact_hash": artifact_hash,
                "request_hash": acceptance_digest(request.model_dump(mode="json")),
                **{k: payload[k] for k in ("authority_actor", "invocation_id", "recorded_at")}}
            session.add(Record(**{k: value[k] for k in ("revision_id", "scope_id", "project_id", "context_id", "previous_revision_id",
                "sequence", "status", "invocation_id")}, payload=value, content_hash=acceptance_digest(value), artifact_ref=artifact_ref))
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=payload["recorded_at"], actor=payload["authority_actor"], actor_kind="user",
                action="quality.test_design_scope.reviewed", entity_type="test_design_scope", entity_id=value["revision_id"], status=value["status"],
                summary="Pinned test-design scope reviewed; no generation, execution or coverage granted.",
                conversation_id=command.conversation_id, tool_invocation_id=command.id, agent_goal_id=command.input_payload.get("agent_goal_id"),
                object_refs=["test_design_scope:" + value["revision_id"]], evidence_refs=[], event_metadata={"context_id": request.context_id}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="quality.test_design_scope.reviewed",
                occurred_at=payload["recorded_at"], correlation_id=request.project_id, entity_type="test_design_scope", entity_id=value["revision_id"],
                entity_version=value["sequence"], mutation_kind="append", patch={k: value[k] for k in ("project_id", "scope_id", "revision_id", "status")},
                query_keys=[["test-design-scope", request.project_id, request.context_id]]), session=session)
            session.flush()
            return value
