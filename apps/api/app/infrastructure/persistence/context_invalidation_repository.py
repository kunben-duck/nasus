from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, text

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.system_image.context_invalidations import ContextInvalidateInput, context_invalidation_query_keys
from ...domain.system_image.context_invalidation import (
    INVALIDATE_CONTEXT_TOOL, INVALIDATION_POLICY, ContextInvalidationIntegrityError,
)
from ...domain.system_image.derivation_impact import DerivationNode, MAX_DEPENDENCIES, validate_derivation_graph
from ...domain.system_image.source_delta import SourceRevisionPin
from ...domain.system_image.source_snapshots import snapshot_digest
from .context_invalidation_models import ContextInvalidationRecord as Record, ContextInvalidationNodeRecord as Node, ContextInvalidationEdgeRecord as Edge
from .context_pack_models import ContextPackRecord
from .db_models import ToolInvocationRecord, ConversationRecord, AgentGoalRecord, UserIdentityRecord, ProjectRoleBindingRecord, AuditEventRecord
from .event_outbox_repository import EventOutboxRepository
from .source_snapshot_repository import SourceSnapshotRepository
from .unit_of_work import session_scope


class ContextInvalidationRepository:
    @staticmethod
    def _lock(session, project_id):
        SourceSnapshotRepository._lock(session, project_id)
        session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"nasus:source-access:{project_id}"})

    @staticmethod
    def _actor(session, project_id, actor_id):
        identity = session.scalar(select(UserIdentityRecord).where(UserIdentityRecord.user_id == actor_id)
            .with_for_update().execution_options(populate_existing=True))
        roles = session.scalars(select(ProjectRoleBindingRecord).where(ProjectRoleBindingRecord.project_id == project_id,
            ProjectRoleBindingRecord.user_id == actor_id, ProjectRoleBindingRecord.version_id.is_(None),
            ProjectRoleBindingRecord.session_id.is_(None), ProjectRoleBindingRecord.status == "active")
            .with_for_update().execution_options(populate_existing=True)).all()
        if (identity is None or identity.status != "active" or identity.role != "platform_admin"
                and (len(roles) != 1 or roles[0].role not in {"qa_lead", "project_admin"})):
            raise PermissionError("context invalidation reviewer membership changed")

    @staticmethod
    def _canonical(session, request, invocation_id, actor_id, *, fresh=False, lock=False):
        query = select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
        row = session.scalar(query.with_for_update() if fresh or lock else query)
        if (row is None or row.tool_id != INVALIDATE_CONTEXT_TOOL or row.status not in {"running", "completed", "failed"}
                or row.input_payload.get("confirmed_by_user") is not True
                or row.input_payload.get("confirmed_actor_id") != actor_id
                or ContextInvalidateInput.model_validate({k: v for k, v in query_payload(row.input_payload).items()
                    if k not in {"confirmed_by_user", "confirmed_at"}}) != request):
            raise ContextInvalidationIntegrityError("invalidation requires its exact canonical request and confirmed actor")
        if row.conversation_id:
            conversation = session.get(ConversationRecord, row.conversation_id)
            if conversation is None or conversation.project_id != request.project_id:
                raise ContextInvalidationIntegrityError("invalidation conversation mismatch")
        if row.input_payload.get("agent_goal_id"):
            goal = session.get(AgentGoalRecord, row.input_payload["agent_goal_id"])
            if goal is None or goal.project_id != request.project_id or goal.conversation_id != row.conversation_id:
                raise ContextInvalidationIntegrityError("invalidation goal mismatch")
        if fresh:
            try:
                confirmed = datetime.fromisoformat(str(row.input_payload.get("confirmed_at", "")))
                valid = confirmed.tzinfo is not None and 0 <= (datetime.now(timezone.utc) - confirmed).total_seconds() <= 900
            except (TypeError, ValueError):
                valid = False
            if row.status != "running" or not valid:
                raise ContextInvalidationIntegrityError("invalidation requires fresh non-future confirmation")
        return row

    @classmethod
    def _value(cls, session, row):
        try:
            return cls._verified_value(session, row)
        except ContextInvalidationIntegrityError:
            raise
        except (ValueError, TypeError, KeyError) as exc:
            raise ContextInvalidationIntegrityError("stored invalidation failed strict validation") from exc

    @classmethod
    def _verified_value(cls, session, row):
        value = row.payload
        request = ContextInvalidateInput.model_validate(value["request"])
        before, after = SourceRevisionPin(**value["before"]), SourceRevisionPin(**value["after"])
        context = session.get(ContextPackRecord, row.context_id)
        if (value.get("schema") != INVALIDATION_POLICY or snapshot_digest(value) != row.content_hash
                or any(value.get(key) != getattr(row, key) for key in ("invalidation_id", "project_id", "context_id", "invocation_id"))
                or request.project_id != row.project_id or request.context_id != row.context_id
                or request.context_artifact_hash != value.get("context_artifact_hash")
                or context is None or context.project_id != row.project_id
                or snapshot_digest(context.payload) != context.content_hash
                or context.payload.get("artifact_hash") != request.context_artifact_hash
                or context.image_revision_id != value.get("image_revision_id")
                or context.payload.get("image_artifact_hash") != value.get("image_artifact_hash")
                or value.get("request_hash") != snapshot_digest(request.model_dump(mode="json"))
                or value.get("impact_hash") != request.expected_impact_hash
                or (before.project_id, before.binding_id) != (row.project_id, row.binding_id)
                or (after.project_id, after.binding_id) != (row.project_id, row.binding_id)
                or before.source_revision_id != row.before_revision_id or request.before_revision_id != row.before_revision_id
                or after.source_revision_id != row.after_revision_id or request.after_revision_id != row.after_revision_id
                or value.get("invalidation_applied") is not True
                or value.get("invalidation_scope") != request.invalidation_scope
                or any(value.get(key) is not False for key in ("impact_complete", "generation_authorized", "execution_authorized"))):
            raise ContextInvalidationIntegrityError("stored invalidation metadata mismatch")
        cls._canonical(session, request, row.invocation_id, value["authority_actor"])
        edges = session.scalars(select(Edge).where(Edge.invalidation_id == row.invalidation_id).limit(MAX_DEPENDENCIES * 2 + 1)).all()
        rows = session.scalars(select(Node).where(Node.invalidation_id == row.invalidation_id).order_by(Node.node_key).limit(MAX_DEPENDENCIES + 1)).all()
        if len(edges) > MAX_DEPENDENCIES * 2 or len(rows) > MAX_DEPENDENCIES:
            raise ContextInvalidationIntegrityError("stored invalidation exceeds its complete graph budget")
        nodes = tuple(DerivationNode(item.kind, item.artifact_id, item.artifact_hash,
            tuple(sorted(edge.parent_key for edge in edges if edge.node_key == item.node_key))) for item in rows)
        graph, _ = validate_derivation_graph(nodes, "context:" + row.context_id)
        if (any(item.node_key != node.key for item, node in zip(rows, nodes))
                or any(edge.node_key not in graph or edge.parent_key not in graph for edge in edges)
                or value.get("dependency_count") != len(nodes)
                or value.get("graph_hash") != snapshot_digest([asdict(node) for node in nodes])
                or graph["context:" + row.context_id].artifact_hash != request.context_artifact_hash):
            raise ContextInvalidationIntegrityError("stored invalidation graph mismatch")
        return {"metadata": value, "dependencies": nodes}

    def get(self, project_id, invalidation_id):
        with session_scope() as session:
            row = session.get(Record, invalidation_id)
            if row is None or row.project_id != project_id:
                raise KeyError("context invalidation not found")
            return self._value(session, row)

    def stale_state(self, project_id, context_id, artifact_hash):
        with session_scope() as session:
            context = session.get(ContextPackRecord, context_id)
            if (context is None or context.project_id != project_id or context.payload.get("artifact_hash") != artifact_hash
                    or snapshot_digest(context.payload) != context.content_hash):
                raise ContextInvalidationIntegrityError("current context invalidation selection mismatch")
            # Fresh IDs/budgets cannot make the same obsolete frozen image current.
            # This never transfers an invalidation to a different image revision.
            row = session.scalar(select(Record).join(ContextPackRecord, ContextPackRecord.context_id == Record.context_id)
                .where(Record.project_id == project_id, ContextPackRecord.project_id == project_id,
                    ContextPackRecord.image_revision_id == context.image_revision_id)
                .order_by(Record.invalidation_id).limit(1))
            if row is None:
                return None
            value = self._value(session, row)["metadata"]
            if value["image_artifact_hash"] != context.payload.get("image_artifact_hash"):
                raise ContextInvalidationIntegrityError("invalidated image digest mismatch")
            return value

    @classmethod
    def _committed(cls, session, request, actor_id, invocation_id):
        row = session.scalar(select(Record).where(Record.invocation_id == invocation_id))
        if row is None:
            return None
        value = cls._value(session, row)["metadata"]
        if value["request"] != request.model_dump(mode="json") or value["authority_actor"] != actor_id:
            raise ContextInvalidationIntegrityError("invalidation invocation already bound")
        return value

    def committed(self, request, *, actor_id, invocation_id, require_access):
        with session_scope() as session:
            self._lock(session, request.project_id)
            self._actor(session, request.project_id, actor_id)
            self._canonical(session, request, invocation_id, actor_id, lock=True)
            value = self._committed(session, request, actor_id, invocation_id)
            require_access()
            return value

    def record(self, request, metadata, nodes, *, require_current, require_access):
        with session_scope() as session:
            self._lock(session, request.project_id)
            self._actor(session, request.project_id, metadata["authority_actor"])
            prior = self._committed(session, request, metadata["authority_actor"], metadata["invocation_id"])
            if prior is not None:
                require_access()
                return prior
            command = self._canonical(session, request, metadata["invocation_id"], metadata["authority_actor"], fresh=True)
            if metadata["request"] != request.model_dump(mode="json"):
                raise ContextInvalidationIntegrityError("invalidation commit request mismatch")
            require_current()
            session.add(Record(**{key: metadata[key] for key in ("invalidation_id", "project_id", "context_id", "invocation_id")},
                binding_id=metadata["before"]["binding_id"], before_revision_id=request.before_revision_id,
                after_revision_id=request.after_revision_id, payload=metadata, content_hash=snapshot_digest(metadata)))
            session.flush()
            session.add_all([Node(invalidation_id=metadata["invalidation_id"], node_key=node.key,
                kind=node.kind, artifact_id=node.artifact_id, artifact_hash=node.artifact_hash) for node in nodes])
            session.flush()
            session.add_all([Edge(invalidation_id=metadata["invalidation_id"], node_key=node.key, parent_key=parent)
                for node in nodes for parent in node.dependencies])
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=metadata["recorded_at"], actor=metadata["authority_actor"], actor_kind="user",
                action=INVALIDATE_CONTEXT_TOOL, entity_type="context_invalidation", entity_id=metadata["invalidation_id"], status="completed",
                summary="Fixed source change invalidated current context use; immutable artifacts and approvals retained.",
                conversation_id=command.conversation_id, tool_invocation_id=command.id,
                agent_goal_id=command.input_payload.get("agent_goal_id"), object_refs=["context_invalidation:" + metadata["invalidation_id"]],
                evidence_refs=[], event_metadata={"context_id": request.context_id}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="system_image.context.invalidated",
                occurred_at=metadata["recorded_at"], correlation_id=request.project_id, entity_type="context_invalidation",
                conversation_id=command.conversation_id, agent_goal_id=command.input_payload.get("agent_goal_id"),
                entity_id=metadata["invalidation_id"], entity_version=1, mutation_kind="append",
                patch={key: metadata[key] for key in ("project_id", "context_id", "invalidation_id", "dependency_count", "graph_hash")},
                snapshot_hint=True, query_keys=context_invalidation_query_keys(request.project_id)), session=session)
            session.flush()
            self._value(session, session.get(Record, metadata["invalidation_id"]))
            require_access()
            return metadata
