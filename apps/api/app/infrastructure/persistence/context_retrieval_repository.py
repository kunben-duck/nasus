from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from ...application.platform.tool_models import EventPayload, ToolResult
from ...application.platform.account_models import UserProfile
from ...application.system_image.context_retrieval_ports import CONTEXT_RETRIEVE_TOOL, ContextRetrievalRequest, UncertainContextBatch
from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from ...domain.system_image.source_snapshots import snapshot_digest
from .context_retrieval_models import ContextRetrievalPlanRecord as Plan, ContextRetrievalCallRecord as Call
from .context_retrieval_models import ContextRetrievalBatchRecord as Batch, ContextRetrievalResultRecord as Result
from .context_retrieval_models import ContextRetrievalCancellationRecord as Cancellation
from .db_models import ToolInvocationRecord, ConversationRecord, AgentGoalRecord, UserIdentityRecord, AuditEventRecord
from .event_outbox_repository import EventOutboxRepository
from .frozen_index_models import FrozenRetrievalRecord
from .source_snapshot_repository import SourceSnapshotRepository
from .unit_of_work import session_scope


class ContextRetrievalRepository:
    def command(self, invocation_id):
        with session_scope() as session:
            row = session.get(ToolInvocationRecord, invocation_id)
            if row is None or row.tool_id != CONTEXT_RETRIEVE_TOOL or row.input_payload.get("confirmed_by_user") is not True:
                raise ImageRevisionIntegrityError("context retrieval command is not confirmed")
            request = ContextRetrievalRequest.model_validate({key: row.input_payload[key]
                for key in ContextRetrievalRequest.model_fields if key in row.input_payload})
            return request, row.status

    def execution(self, invocation_id):
        with session_scope() as session:
            row = session.get(ToolInvocationRecord, invocation_id)
            if row is None or row.tool_id != CONTEXT_RETRIEVE_TOOL or row.input_payload.get("confirmed_by_user") is not True:
                raise ImageRevisionIntegrityError("context retrieval command is not confirmed")
            actor = session.get(UserIdentityRecord, row.input_payload.get("confirmed_actor_id", ""))
            if actor is None or actor.status != "active":
                raise ImageRevisionIntegrityError("context retrieval confirming account is unavailable")
            request = ContextRetrievalRequest.model_validate({key: row.input_payload[key]
                for key in ContextRetrievalRequest.model_fields if key in row.input_payload})
            return request, row.status, UserProfile(id=actor.user_id, name=actor.display_name, email=actor.email, role=actor.role)

    def pending(self, *, after_id=None, limit=100):
        with session_scope() as session:
            statement = select(ToolInvocationRecord).where(ToolInvocationRecord.tool_id == CONTEXT_RETRIEVE_TOOL,
                ToolInvocationRecord.status == "running")
            if after_id is not None:
                statement = statement.where(ToolInvocationRecord.id > after_id)
            return [(row.id, row.input_payload.get("project_id")) for row in session.scalars(
                statement.order_by(ToolInvocationRecord.id).limit(min(max(limit, 1), 100)))]

    def pending_cancellations(self, *, after_id=None, limit=100):
        with session_scope() as session:
            statement = select(Cancellation).where(Cancellation.delivered_at.is_(None))
            if after_id is not None:
                statement = statement.where(Cancellation.invocation_id > after_id)
            return [(row.invocation_id, row.project_id) for row in session.scalars(
                statement.order_by(Cancellation.invocation_id).limit(min(max(limit, 1), 100)))]

    def cancellation_delivered(self, project_id, invocation_id):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, project_id)
            row = session.get(Cancellation, invocation_id)
            command = session.get(ToolInvocationRecord, invocation_id)
            if (row is None or row.project_id != project_id or command is None
                    or command.tool_id != CONTEXT_RETRIEVE_TOOL or command.status != "cancelled"
                    or command.input_payload.get("project_id") != project_id):
                raise ImageRevisionIntegrityError("context retrieval cancellation receipt scope mismatch")
            if row.delivered_at is None:
                row.delivered_at = datetime.now(timezone.utc)
                self._event(session, project_id, invocation_id, "cancel_delivered")

    def finish(self, project_id, invocation_id, status, summary):
        if status not in {"failed", "cancelled"}:
            raise ValueError("invalid retrieval termination")
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, project_id)
            row = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
            if row is None or row.tool_id != CONTEXT_RETRIEVE_TOOL or row.input_payload.get("project_id") != project_id:
                raise ImageRevisionIntegrityError("context retrieval termination scope mismatch")
            if row.status == "running":
                self._terminal(session, row, status, summary)
            if row.status == "cancelled" and session.get(Cancellation, invocation_id) is None:
                session.add(Cancellation(invocation_id=invocation_id, project_id=project_id,
                    requested_at=datetime.now(timezone.utc)))
                self._event(session, project_id, invocation_id, "cancel_requested")
            return row.status

    @staticmethod
    def _terminal(session, row, status, summary):
        row.status, row.summary = status, summary
        row.revision += 1
        refs = [f"context_retrieval:{row.id}"] if status == "completed" else []
        row.result_payload = ToolResult(invocation_id=row.id, status=status, summary=summary, object_refs=refs).model_dump()
        session.add(AuditEventRecord(id=str(uuid4()), occurred_at=datetime.now(timezone.utc).isoformat(),
            actor=row.input_payload.get("confirmed_actor_id", "system"), actor_kind="system",
            action=f"tool.invocation.{status}", entity_type="tool_invocation", entity_id=row.id, status=status,
            summary=summary, conversation_id=row.conversation_id, tool_invocation_id=row.id,
            agent_goal_id=row.input_payload.get("agent_goal_id"), object_refs=refs, evidence_refs=[], event_metadata={}))
        EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="tool.invocation.updated",
            occurred_at=datetime.now(timezone.utc).isoformat(), correlation_id=row.conversation_id or row.id,
            conversation_id=row.conversation_id, agent_goal_id=row.input_payload.get("agent_goal_id"),
            entity_type="tool_invocation", entity_id=row.id, entity_version=0, mutation_kind="replace",
            patch={"status": status, "summary": summary, "tool_id": row.tool_id},
            query_keys=[["tool-invocation", row.id], ["context-retrieval", row.input_payload["project_id"], row.id]]), session=session)

    @staticmethod
    def _command(session, request, invocation_id, actor_id, *, lock=True):
        statement = select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
        row = session.scalar(statement.with_for_update() if lock else statement)
        if (row is None or row.tool_id != CONTEXT_RETRIEVE_TOOL or row.status != "running"
                or row.input_payload.get("confirmed_by_user") is not True
                or row.input_payload.get("confirmed_actor_id") != actor_id
                or any(row.input_payload.get(key) != value for key, value in request.model_dump().items())):
            raise ImageRevisionIntegrityError("context retrieval requires its confirmed canonical actor and request")
        if row.conversation_id:
            conversation = session.get(ConversationRecord, row.conversation_id)
            if conversation is None or conversation.project_id != request.project_id:
                raise ImageRevisionIntegrityError("context retrieval conversation mismatch")
        goal_id = row.input_payload.get("agent_goal_id")
        if goal_id:
            goal = session.get(AgentGoalRecord, goal_id)
            if goal is None or (goal.project_id, goal.conversation_id) != (request.project_id, row.conversation_id):
                raise ImageRevisionIntegrityError("context retrieval goal mismatch")
        return row

    @staticmethod
    def _plan(row):
        body = row.payload
        if (snapshot_digest(body) != row.content_hash or body["invocation_id"] != row.invocation_id
                or body["request"]["project_id"] != row.project_id or body["request"]["generation_id"] != row.generation_id
                or body["actor_id"] != row.actor_id or body["preview"]["plan_digest"] != body["request"]["expected_plan_digest"]):
            raise ImageRevisionIntegrityError("context retrieval plan integrity mismatch")
        return body

    def require_running(self, request, invocation_id, actor_id):
        with session_scope() as session:
            self._command(session, request, invocation_id, actor_id, lock=False)

    def prepare(self, request, preview, *, invocation_id, actor_id, require_current):
        payload = {"invocation_id": invocation_id, "request": request.model_dump(), "preview": preview, "actor_id": actor_id}
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            command = self._command(session, request, invocation_id, actor_id)
            existing = session.get(Plan, invocation_id)
            if existing is not None:
                if self._plan(existing) != payload:
                    raise ImageRevisionIntegrityError("context retrieval plan changed")
            else:
                confirmed = datetime.fromisoformat(str(command.input_payload.get("confirmed_at", "")))
                if confirmed.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - confirmed).total_seconds() <= 900:
                    raise ValueError("context retrieval consent expired")
                if preview["plan_digest"] != request.expected_plan_digest or preview["query_count"] < 1:
                    raise ImageRevisionIntegrityError("context retrieval needs the complete nonempty confirmed query plan")
                session.add(Plan(invocation_id=invocation_id, project_id=request.project_id, generation_id=request.generation_id,
                    actor_id=actor_id, payload=payload, content_hash=snapshot_digest(payload)))
                self._event(session, request.project_id, invocation_id, "prepared")
            session.flush()
            require_current()

    def batch(self, project_id, invocation_id, ordinal):
        with session_scope() as session:
            call = session.get(Call, (invocation_id, ordinal))
            batch = session.get(Batch, (invocation_id, ordinal))
            if call is None:
                return None
            if call.project_id != project_id or (batch and batch.project_id != project_id):
                raise ImageRevisionIntegrityError("context retrieval batch project mismatch")
            return {"input_digest": call.input_digest, "owner": call.owner, "expires_at": call.expires_at,
                "artifact_ref": batch.artifact_ref if batch else None, "artifact_hash": batch.artifact_hash if batch else None}

    def reserve_batch(self, request, invocation_id, ordinal, input_digest, owner, *, actor_id, require_current):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            self._command(session, request, invocation_id, actor_id)
            plan = session.get(Plan, invocation_id)
            if plan is None or self._plan(plan)["request"] != request.model_dump():
                raise ImageRevisionIntegrityError("context batch needs its original prepared plan")
            if type(ordinal) is not int or not 0 <= ordinal < plan.payload["preview"]["max_model_calls"]:
                raise ImageRevisionIntegrityError("context batch exceeds the confirmed call budget")
            if session.get(Call, (invocation_id, ordinal)) is not None:
                return False
            session.add(Call(invocation_id=invocation_id, ordinal=ordinal, project_id=request.project_id,
                input_digest=input_digest, owner=owner, expires_at=datetime.now(timezone.utc) + timedelta(seconds=120)))
            self._event(session, request.project_id, invocation_id, "batch_reserved", ordinal)
            session.flush()
            require_current()
            return True

    def complete_batch(self, request, invocation_id, ordinal, owner, artifact_ref, artifact_hash, *, actor_id, require_current):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            self._command(session, request, invocation_id, actor_id)
            call = session.get(Call, (invocation_id, ordinal))
            if call is None or call.project_id != request.project_id or call.owner != owner or call.expires_at <= datetime.now(timezone.utc):
                raise UncertainContextBatch("context batch reservation is missing, expired or owned by another attempt")
            existing = session.get(Batch, (invocation_id, ordinal))
            if existing:
                if (existing.artifact_ref, existing.artifact_hash) != (artifact_ref, artifact_hash):
                    raise ImageRevisionIntegrityError("context batch result changed")
            else:
                session.add(Batch(invocation_id=invocation_id, ordinal=ordinal, project_id=request.project_id,
                    artifact_ref=artifact_ref, artifact_hash=artifact_hash))
                self._event(session, request.project_id, invocation_id, "batch_completed", ordinal)
            session.flush()
            require_current()

    def result(self, project_id, invocation_id):
        with session_scope() as session:
            row = session.get(Result, invocation_id)
            if row is None:
                return None
            plan = session.get(Plan, invocation_id)
            if (row.project_id != project_id or plan is None or snapshot_digest(row.payload) != row.content_hash):
                raise ImageRevisionIntegrityError("context retrieval result integrity mismatch")
            return {"metadata": row.payload, "plan": self._plan(plan), "artifact_ref": row.artifact_ref, "artifact_hash": row.artifact_hash}

    def complete(self, request, invocation_id, traces, metadata, artifact_ref, artifact_hash, *, actor_id, require_current):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            self._command(session, request, invocation_id, actor_id)
            plan = session.get(Plan, invocation_id)
            if plan is None or self._plan(plan)["request"] != request.model_dump() or plan.actor_id != actor_id:
                raise ImageRevisionIntegrityError("context retrieval commit lacks its prepared plan")
            preview = plan.payload["preview"]
            bindings = metadata["retrieval_bindings"]
            if (metadata.get("project_id") != request.project_id or metadata.get("invocation_id") != invocation_id
                    or metadata.get("generation_id") != request.generation_id
                    or any(metadata.get(key) != preview[key] for key in ("publication_pin", "model", "plan_digest", "queries_digest", "query_count", "index_artifact_hash"))
                    or any(metadata.get(key) is not False for key in ("relationship_authority", "quality_generation_authorized", "rerank_egress_authorized"))
                    or len(bindings) != preview["query_count"] or set(bindings.values()) != {item["retrieval_id"] for item in traces}
                    or len(traces) != len(bindings) or len(set(bindings.values())) != len(bindings)
                    or any(item["project_id"] != request.project_id or item["generation_id"] != request.generation_id
                        or item["publication_id"] != request.publication_id or item["actor_id"] != actor_id for item in traces)):
                raise ImageRevisionIntegrityError("context retrieval mapping is incomplete or cross-scope")
            if any(session.get(Batch, (invocation_id, ordinal)) is None for ordinal in range(preview["max_model_calls"])):
                raise ImageRevisionIntegrityError("context retrieval has unfinished provider batches")
            existing = session.get(Result, invocation_id)
            if existing:
                if existing.payload != metadata or existing.artifact_hash != artifact_hash:
                    raise ImageRevisionIntegrityError("context retrieval completion changed")
                require_current()
                return
            for trace in traces:
                row = FrozenRetrievalRecord(**trace)
                session.add(row)
                session.flush()
                from .retrieval_provenance_projection_v1 import RetrievalProvenanceProjectorV1
                RetrievalProvenanceProjectorV1().fact(session, "retrieval", row, write=True)
            session.add(Result(invocation_id=invocation_id, project_id=request.project_id, payload=metadata,
                content_hash=snapshot_digest(metadata), artifact_ref=artifact_ref, artifact_hash=artifact_hash))
            self._event(session, request.project_id, invocation_id, "completed")
            session.flush()
            require_current()
            command = self._command(session, request, invocation_id, actor_id)
            self._terminal(session, command, "completed",
                "All frozen AC retrieval traces committed. Recall is not relationship, oracle, coverage or generation approval.")

    @staticmethod
    def _event(session, project_id, invocation_id, state, ordinal=None):
        EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=f"system_image.context_retrieval.{state}",
            occurred_at=datetime.now(timezone.utc).isoformat(), correlation_id=project_id, entity_type="context_retrieval",
            entity_id=invocation_id, entity_version=0, mutation_kind="append", patch={"project_id": project_id, "ordinal": ordinal},
            query_keys=[["context-retrieval", project_id, invocation_id]]), session=session)
