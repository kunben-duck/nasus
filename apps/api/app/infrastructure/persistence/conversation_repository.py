from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from .db_models import (
    AuditEventRecord,
    AgentGoalRecord,
    AgentMemoryItemRecord,
    AgentMemoryLinkRecord,
    AgentSwarmRunRecord,
    AgentWorkerAssignmentRecord,
    ConversationMessageRecord,
    ConversationLinkRecord,
    ConversationRecord,
    ConversationSummaryCheckpointRecord,
    SessionKnowledgeBindingRecord,
    ToolInvocationRecord,
)
from .unit_of_work import session_scope
from ...application.agent.agent_models import (
    AgentGoal,
    AgentMemoryItem,
    AgentMemoryLink,
    AgentStep,
    AgentSwarmRun,
    AgentWorkerAssignment,
    ConversationMessage,
    ConversationLink,
    ConversationSession,
    ConversationSummaryCheckpoint,
    MessageBlock,
    SessionKnowledgeBinding,
)
from ...application.platform.tool_models import AuditEvent, ToolInvocation, ToolResult

__all__ = ["ConversationRepository"]


class ConversationRepository:
    def find_conversation(
        self,
        *,
        space_type: str,
        space_id: str,
        project_id: str | None = None,
        initiator_id: str | None = None,
    ) -> ConversationSession | None:
        """Resolve the canonical conversation for one user or project scope."""

        with session_scope() as session:
            statement = select(ConversationRecord).where(
                ConversationRecord.space_type == space_type,
                ConversationRecord.space_id == space_id,
            )
            if project_id is not None:
                statement = statement.where(
                    ConversationRecord.project_id == project_id
                )
            elif initiator_id is not None:
                statement = statement.where(
                    ConversationRecord.project_id.is_(None),
                    ConversationRecord.initiator_id == initiator_id,
                )
            else:
                return None
            row = session.scalar(statement.order_by(ConversationRecord.id).limit(1))
            conversation_id = row.id if row is not None else None
        return (
            self.get_conversation(conversation_id)
            if conversation_id is not None
            else None
        )

    def load_all(self) -> list[ConversationSession]:
        with session_scope() as session:
            conversations = session.scalars(select(ConversationRecord)).all()
            message_rows = session.scalars(select(ConversationMessageRecord)).all()
            goal_rows = session.scalars(select(AgentGoalRecord)).all()
            invocation_rows = session.scalars(select(ToolInvocationRecord)).all()

        messages_by_conversation: dict[str, list[ConversationMessage]] = {}
        for row in message_rows:
            messages_by_conversation.setdefault(row.conversation_id, []).append(self._to_message(row))
        for items in messages_by_conversation.values():
            items.sort(key=lambda item: item.created_at)

        goals_by_conversation: dict[str, list[AgentGoal]] = {}
        for row in goal_rows:
            goals_by_conversation.setdefault(row.conversation_id, []).append(self._to_goal(row))

        invocations_by_conversation: dict[str, list[ToolInvocation]] = {}
        for row in invocation_rows:
            if row.conversation_id:
                invocations_by_conversation.setdefault(row.conversation_id, []).append(self._to_tool_invocation(row))

        return [
            self._to_conversation(
                row,
                messages_by_conversation.get(row.id, []),
                goals_by_conversation.get(row.id, []),
                invocations_by_conversation.get(row.id, []),
            )
            for row in conversations
        ]

    def get_conversation(self, conversation_id: str) -> ConversationSession | None:
        with session_scope() as session:
            conversation = session.get(ConversationRecord, conversation_id)
            if conversation is None:
                return None
            message_rows = session.scalars(
                select(ConversationMessageRecord).where(
                    ConversationMessageRecord.conversation_id == conversation_id
                )
            ).all()
            goal_rows = session.scalars(
                select(AgentGoalRecord).where(
                    AgentGoalRecord.conversation_id == conversation_id
                )
            ).all()
            invocation_rows = session.scalars(
                select(ToolInvocationRecord).where(
                    ToolInvocationRecord.conversation_id == conversation_id
                )
            ).all()

        messages = sorted(
            (self._to_message(row) for row in message_rows),
            key=lambda item: item.created_at,
        )
        return self._to_conversation(
            conversation,
            messages,
            [self._to_goal(row) for row in goal_rows],
            [self._to_tool_invocation(row) for row in invocation_rows],
        )

    def upsert_conversation(self, conversation: ConversationSession) -> None:
        with session_scope() as session:
            record = session.get(ConversationRecord, conversation.id)
            if record is None:
                record = ConversationRecord(id=conversation.id)
                session.add(record)

            record.session_id = conversation.session_id
            record.title = conversation.title
            record.space_type = conversation.space_type
            record.space_id = conversation.space_id
            record.project_id = conversation.project_id
            record.version_id = conversation.version_id
            record.us_id = conversation.us_id
            record.task_id = conversation.task_id
            record.initiator_id = conversation.initiator_id
            record.status = conversation.status
            record.last_message_at = conversation.last_message_at
            record.latest_summary_checkpoint_id = conversation.latest_summary_checkpoint_id
            record.merged_into_conversation_id = conversation.merged_into_conversation_id
            record.archived_at = conversation.archived_at
            record.related_conversation_ids = conversation.related_conversation_ids

    def load_conversation_links(self) -> list[ConversationLink]:
        with session_scope() as session:
            rows = session.scalars(
                select(ConversationLinkRecord).order_by(
                    ConversationLinkRecord.created_at
                )
            ).all()
        return [self._to_conversation_link(row) for row in rows]

    def upsert_conversation_link(self, link: ConversationLink) -> None:
        with session_scope() as session:
            record = session.get(ConversationLinkRecord, link.id)
            if record is None:
                record = ConversationLinkRecord(id=link.id)
                session.add(record)

            record.left_conversation_id = link.left_conversation_id
            record.right_conversation_id = link.right_conversation_id
            record.link_kind = link.link_kind
            record.reason = link.reason
            record.confidence = link.confidence
            record.created_at = link.created_at

    def append_message(self, conversation_id: str, message: ConversationMessage) -> None:
        with session_scope() as session:
            record = ConversationMessageRecord(
                id=message.id,
                conversation_id=conversation_id,
                role=message.role,
                status=message.status,
                content_type=message.content_type,
                created_at=message.created_at,
                blocks=[block.model_dump() for block in message.blocks],
                tool_refs=message.tool_refs,
                object_refs=message.object_refs,
                message_metadata=message.metadata,
                stream_id=message.stream_id,
                sequence_max=message.sequence_max,
            )
            session.add(record)

            conversation = session.get(ConversationRecord, conversation_id)
            if conversation is not None:
                conversation.last_message_at = message.created_at
                if conversation.status in {"draft", "idle"}:
                    conversation.status = "active"

    def replace_goals(self, conversation_id: str, goals: list[AgentGoal]) -> None:
        with session_scope() as session:
            session.execute(delete(AgentGoalRecord).where(AgentGoalRecord.conversation_id == conversation_id))
            for goal in goals:
                session.add(
                    AgentGoalRecord(
                        id=goal.id,
                        conversation_id=goal.conversation_id,
                        project_id=goal.project_id,
                        us_id=goal.us_id,
                        goal_template=goal.goal_template,
                        goal_description=goal.goal_description,
                        target_refs=goal.target_refs,
                        query_keys=goal.query_keys,
                        planner_kind=goal.planner_kind,
                        planning_summary=goal.planning_summary,
                        title=goal.title,
                        status=goal.status,
                        summary=goal.summary,
                        steps=[step.model_dump() for step in goal.steps],
                        autonomy_level=goal.autonomy_level,
                        max_steps=goal.max_steps,
                        max_model_calls=goal.max_model_calls,
                        max_thinking_tokens=goal.max_thinking_tokens,
                        max_runtime_seconds=goal.max_runtime_seconds,
                        max_no_progress_observations=goal.max_no_progress_observations,
                        steps_completed=goal.steps_completed,
                        model_calls_used=goal.model_calls_used,
                        thinking_input_tokens_used=goal.thinking_input_tokens_used,
                        thinking_output_tokens_used=goal.thinking_output_tokens_used,
                        thinking_tokens_used=goal.thinking_tokens_used,
                        no_progress_observations=goal.no_progress_observations,
                        started_at=goal.started_at,
                        last_progress_at=goal.last_progress_at,
                        last_progress_fingerprint=goal.last_progress_fingerprint,
                        budget_exhausted_reason=goal.budget_exhausted_reason,
                        pause_reason=goal.pause_reason,
                        workflow_id=goal.workflow_id,
                    )
                )

    def upsert_goal(self, goal: AgentGoal) -> None:
        with session_scope() as session:
            record = session.get(AgentGoalRecord, goal.id)
            if record is None:
                record = AgentGoalRecord(id=goal.id, conversation_id=goal.conversation_id)
                session.add(record)

            record.conversation_id = goal.conversation_id
            record.project_id = goal.project_id
            record.us_id = goal.us_id
            record.goal_template = goal.goal_template
            record.goal_description = goal.goal_description
            record.target_refs = goal.target_refs
            record.query_keys = goal.query_keys
            record.planner_kind = goal.planner_kind
            record.planning_summary = goal.planning_summary
            record.title = goal.title
            record.status = goal.status
            record.summary = goal.summary
            record.steps = [step.model_dump() for step in goal.steps]
            record.autonomy_level = goal.autonomy_level
            record.max_steps = goal.max_steps
            record.max_model_calls = goal.max_model_calls
            record.max_thinking_tokens = goal.max_thinking_tokens
            record.max_runtime_seconds = goal.max_runtime_seconds
            record.max_no_progress_observations = goal.max_no_progress_observations
            record.steps_completed = goal.steps_completed
            record.model_calls_used = goal.model_calls_used
            record.thinking_input_tokens_used = goal.thinking_input_tokens_used
            record.thinking_output_tokens_used = goal.thinking_output_tokens_used
            record.thinking_tokens_used = goal.thinking_tokens_used
            record.no_progress_observations = goal.no_progress_observations
            record.started_at = goal.started_at
            record.last_progress_at = goal.last_progress_at
            record.last_progress_fingerprint = goal.last_progress_fingerprint
            record.budget_exhausted_reason = goal.budget_exhausted_reason
            record.pause_reason = goal.pause_reason
            record.workflow_id = goal.workflow_id

    def get_agent_goal(self, goal_id: str) -> AgentGoal | None:
        with session_scope() as session:
            row = session.get(AgentGoalRecord, goal_id)
            return self._to_goal(row) if row is not None else None

    def list_agent_goals(
        self,
        *,
        conversation_id: str | None = None,
    ) -> list[AgentGoal]:
        with session_scope() as session:
            statement = select(AgentGoalRecord)
            if conversation_id is not None:
                statement = statement.where(
                    AgentGoalRecord.conversation_id == conversation_id
                )
            rows = session.scalars(
                statement.order_by(AgentGoalRecord.id)
            ).all()
        return [self._to_goal(row) for row in rows]

    def load_tool_invocations(self) -> list[ToolInvocation]:
        with session_scope() as session:
            rows = session.scalars(select(ToolInvocationRecord)).all()
        return [self._to_tool_invocation(row) for row in rows]

    def get_tool_invocation(self, invocation_id: str) -> ToolInvocation | None:
        with session_scope() as session:
            row = session.get(ToolInvocationRecord, invocation_id)
            return self._to_tool_invocation(row) if row is not None else None

    def find_idempotent_tool_invocation(
        self,
        *,
        idempotency_scope: str,
        tool_id: str,
        idempotency_key: str,
    ) -> ToolInvocation | None:
        with session_scope() as session:
            row = session.scalar(
                select(ToolInvocationRecord).where(
                    ToolInvocationRecord.idempotency_scope == idempotency_scope,
                    ToolInvocationRecord.tool_id == tool_id,
                    ToolInvocationRecord.idempotency_key == idempotency_key,
                )
            )
            return self._to_tool_invocation(row) if row is not None else None

    def create_tool_invocation(self, invocation: ToolInvocation) -> ToolInvocation:
        """Insert one invocation, resolving concurrent idempotent creates."""
        try:
            with session_scope() as session:
                session.add(self._new_tool_invocation_record(invocation))
                session.flush()
        except IntegrityError:
            if not (
                invocation.idempotency_scope
                and invocation.idempotency_key
            ):
                raise
            existing = self.find_idempotent_tool_invocation(
                idempotency_scope=invocation.idempotency_scope,
                tool_id=invocation.tool_id,
                idempotency_key=invocation.idempotency_key,
            )
            if existing is None:
                raise
            return existing
        return invocation

    def claim_tool_invocation_for_execution(
        self,
        invocation_id: str,
        *,
        expected_statuses: tuple[str, ...],
        input_updates: dict | None = None,
    ) -> ToolInvocation | None:
        """Serialize execution claims with a row lock in PostgreSQL."""
        with session_scope() as session:
            row = session.scalar(
                select(ToolInvocationRecord)
                .where(ToolInvocationRecord.id == invocation_id)
                .with_for_update()
            )
            if row is None:
                raise KeyError(invocation_id)
            if row.status not in expected_statuses:
                return None
            payload = dict(row.input_payload or {})
            payload.update(input_updates or {})
            row.input_payload = payload
            row.status = "running"
            row.revision = int(row.revision or 0) + 1
            session.flush()
            claimed = self._to_tool_invocation(row)
        return claimed

    def load_audit_events(self) -> list[AuditEvent]:
        with session_scope() as session:
            rows = session.scalars(select(AuditEventRecord).order_by(AuditEventRecord.occurred_at)).all()
        return [self._to_audit_event(row) for row in rows]

    def load_agent_swarms(self) -> list[AgentSwarmRun]:
        return self.list_agent_swarms()

    def list_agent_swarms(
        self,
        *,
        conversation_id: str | None = None,
        parent_goal_id: str | None = None,
    ) -> list[AgentSwarmRun]:
        with session_scope() as session:
            statement = select(AgentSwarmRunRecord)
            if conversation_id:
                statement = statement.where(AgentSwarmRunRecord.conversation_id == conversation_id)
            if parent_goal_id:
                statement = statement.where(AgentSwarmRunRecord.parent_goal_id == parent_goal_id)
            statement = statement.order_by(AgentSwarmRunRecord.created_at, AgentSwarmRunRecord.id)
            swarm_rows = session.scalars(statement).all()
            swarm_ids = [row.id for row in swarm_rows]
            if not swarm_ids:
                return []
            assignment_rows = session.scalars(
                select(AgentWorkerAssignmentRecord)
                .where(AgentWorkerAssignmentRecord.swarm_run_id.in_(swarm_ids))
                .order_by(AgentWorkerAssignmentRecord.swarm_run_id, AgentWorkerAssignmentRecord.id)
            ).all()

        assignments_by_swarm: dict[str, list[AgentWorkerAssignment]] = {}
        for row in assignment_rows:
            assignments_by_swarm.setdefault(row.swarm_run_id, []).append(self._to_assignment(row))

        return [
            self._to_swarm(row, assignments_by_swarm.get(row.id, []))
            for row in swarm_rows
        ]

    def get_agent_swarm(self, swarm_id: str) -> AgentSwarmRun | None:
        with session_scope() as session:
            row = session.get(AgentSwarmRunRecord, swarm_id)
            if row is None:
                return None
            assignment_rows = session.scalars(
                select(AgentWorkerAssignmentRecord)
                .where(AgentWorkerAssignmentRecord.swarm_run_id == swarm_id)
                .order_by(AgentWorkerAssignmentRecord.id)
            ).all()
        return self._to_swarm(
            row,
            [self._to_assignment(assignment) for assignment in assignment_rows],
        )

    def load_agent_memory_items(self) -> list[AgentMemoryItem]:
        with session_scope() as session:
            rows = session.scalars(
                select(AgentMemoryItemRecord).order_by(AgentMemoryItemRecord.created_at)
            ).all()
        return [self._to_agent_memory_item(row) for row in rows]

    def list_agent_memory_items(
        self,
        *,
        owner_ref: str | None = None,
        memory_scope: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[AgentMemoryItem]:
        """Load a scoped memory slice without scanning other project owners."""

        statement = select(AgentMemoryItemRecord)
        if owner_ref is not None:
            statement = statement.where(AgentMemoryItemRecord.owner_ref == owner_ref)
        if memory_scope is not None:
            statement = statement.where(AgentMemoryItemRecord.memory_scope == memory_scope)
        if status is not None:
            statement = statement.where(AgentMemoryItemRecord.status == status)
        statement = statement.order_by(AgentMemoryItemRecord.created_at.desc())
        if limit is not None:
            statement = statement.limit(max(0, limit))
        with session_scope() as session:
            rows = session.scalars(statement).all()
        return [self._to_agent_memory_item(row) for row in reversed(rows)]

    def load_agent_memory_links(self) -> list[AgentMemoryLink]:
        with session_scope() as session:
            rows = session.scalars(
                select(AgentMemoryLinkRecord).order_by(AgentMemoryLinkRecord.created_at)
            ).all()
        return [self._to_agent_memory_link(row) for row in rows]

    def upsert_agent_memory_item(self, item: AgentMemoryItem) -> None:
        with session_scope() as session:
            record = session.get(AgentMemoryItemRecord, item.id)
            if record is None:
                record = AgentMemoryItemRecord(id=item.id)
                session.add(record)

            record.memory_scope = item.memory_scope
            record.owner_ref = item.owner_ref
            record.source_refs = item.source_refs
            record.summary = item.summary
            record.object_refs = item.object_refs
            record.evidence_refs = item.evidence_refs
            record.status = item.status
            record.expires_at = item.expires_at
            record.created_at = item.created_at

    def upsert_agent_memory_link(self, link: AgentMemoryLink) -> None:
        with session_scope() as session:
            record = session.get(AgentMemoryLinkRecord, link.id)
            if record is None:
                record = AgentMemoryLinkRecord(id=link.id)
                session.add(record)

            record.memory_id = link.memory_id
            record.target_ref = link.target_ref
            record.link_kind = link.link_kind
            record.confidence = link.confidence
            record.created_at = link.created_at

    def upsert_agent_swarm(self, swarm: AgentSwarmRun) -> None:
        with session_scope() as session:
            record = session.get(AgentSwarmRunRecord, swarm.id)
            if record is None:
                record = AgentSwarmRunRecord(id=swarm.id)
                session.add(record)

            record.parent_goal_id = swarm.parent_goal_id
            record.conversation_id = swarm.conversation_id
            record.swarm_kind = swarm.swarm_kind
            record.status = swarm.status
            record.max_parallel_agents = swarm.max_parallel_agents
            record.budget_ref = swarm.budget_ref
            record.merge_strategy = swarm.merge_strategy
            record.target_refs = swarm.target_refs
            record.result_summary = swarm.result_summary
            record.created_at = swarm.created_at
            record.completed_at = swarm.completed_at

            for assignment in swarm.assignments:
                assignment_record = session.get(AgentWorkerAssignmentRecord, assignment.id)
                if assignment_record is None:
                    assignment_record = AgentWorkerAssignmentRecord(id=assignment.id, swarm_run_id=swarm.id)
                    session.add(assignment_record)
                assignment_record.swarm_run_id = assignment.swarm_run_id
                assignment_record.worker_agent_kind = assignment.worker_agent_kind
                assignment_record.target_refs = assignment.target_refs
                assignment_record.input_context_refs = assignment.input_context_refs
                assignment_record.status = assignment.status
                assignment_record.agent_goal_id = assignment.agent_goal_id
                assignment_record.tool_invocation_refs = assignment.tool_invocation_refs
                assignment_record.candidate_result_ref = assignment.candidate_result_ref
                assignment_record.timeout_seconds = assignment.timeout_seconds
                assignment_record.confidence = assignment.confidence
                assignment_record.summary = assignment.summary
                assignment_record.created_at = assignment.created_at
                assignment_record.completed_at = assignment.completed_at

    def load_summary_checkpoints(self) -> list[ConversationSummaryCheckpoint]:
        with session_scope() as session:
            rows = session.scalars(
                select(ConversationSummaryCheckpointRecord).order_by(ConversationSummaryCheckpointRecord.created_at)
            ).all()
        return [self._to_summary_checkpoint(row) for row in rows]

    def upsert_summary_checkpoint(self, checkpoint: ConversationSummaryCheckpoint) -> None:
        with session_scope() as session:
            record = session.get(ConversationSummaryCheckpointRecord, checkpoint.id)
            if record is None:
                record = ConversationSummaryCheckpointRecord(id=checkpoint.id)
                session.add(record)

            record.conversation_id = checkpoint.conversation_id
            record.message_range_start = checkpoint.message_range_start
            record.message_range_end = checkpoint.message_range_end
            record.summary_text = checkpoint.summary_text
            record.summary_object_refs = checkpoint.summary_object_refs
            record.summary_token_count = checkpoint.summary_token_count
            record.created_by = checkpoint.created_by
            record.created_at = checkpoint.created_at

    def load_session_knowledge_bindings(self) -> list[SessionKnowledgeBinding]:
        with session_scope() as session:
            rows = session.scalars(
                select(SessionKnowledgeBindingRecord).order_by(SessionKnowledgeBindingRecord.created_at)
            ).all()
        return [self._to_session_knowledge_binding(row) for row in rows]

    def upsert_session_knowledge_binding(self, binding: SessionKnowledgeBinding) -> None:
        with session_scope() as session:
            record = session.get(SessionKnowledgeBindingRecord, binding.id)
            if record is None:
                record = SessionKnowledgeBindingRecord(id=binding.id)
                session.add(record)

            record.conversation_id = binding.conversation_id
            record.candidate_object_ref = binding.candidate_object_ref
            record.scope = binding.scope
            record.created_at = binding.created_at

    def upsert_tool_invocation(self, invocation: ToolInvocation) -> None:
        with session_scope() as session:
            record = session.get(ToolInvocationRecord, invocation.id)
            if record is None:
                record = ToolInvocationRecord(id=invocation.id)
                session.add(record)

            record.conversation_id = invocation.conversation_id
            record.tool_id = invocation.tool_id
            record.status = invocation.status
            record.summary = invocation.summary
            record.initiator_surface = invocation.initiator_surface
            record.initiator_actor = invocation.initiator_actor
            record.target_scope = invocation.target_scope
            record.input_payload = invocation.input_payload
            record.result_payload = invocation.result.model_dump() if invocation.result else None
            record.idempotency_scope = invocation.idempotency_scope
            record.idempotency_key = invocation.idempotency_key
            record.idempotency_fingerprint = invocation.idempotency_fingerprint
            record.revision = max(int(record.revision or 0), invocation.revision)

    def append_audit_event(self, event: AuditEvent) -> None:
        """Append an immutable audit fact; identical retries are idempotent."""

        try:
            with session_scope() as session:
                record = session.get(AuditEventRecord, event.id)
                if record is not None:
                    self._assert_same_audit_event(record, event)
                    return
                session.add(self._new_audit_event_record(event))
        except IntegrityError:
            # A concurrent writer may have committed the same event ID after
            # this transaction checked for it. Accept only an identical retry.
            with session_scope() as session:
                record = session.get(AuditEventRecord, event.id)
                if record is None:
                    raise
                self._assert_same_audit_event(record, event)

    def upsert_audit_event(self, event: AuditEvent) -> None:
        """Compatibility alias; audit facts are append-only."""

        self.append_audit_event(event)

    def _to_conversation(
        self,
        row: ConversationRecord,
        messages: list[ConversationMessage],
        goals: list[AgentGoal],
        tool_invocations: list[ToolInvocation],
    ) -> ConversationSession:
        return ConversationSession(
            id=row.id,
            session_id=row.session_id,
            title=row.title,
            space_type=row.space_type,
            space_id=row.space_id,
            project_id=row.project_id,
            version_id=row.version_id,
            us_id=row.us_id,
            task_id=row.task_id,
            initiator_id=row.initiator_id,
            status=row.status,
            last_message_at=row.last_message_at,
            latest_summary_checkpoint_id=row.latest_summary_checkpoint_id,
            merged_into_conversation_id=row.merged_into_conversation_id,
            archived_at=row.archived_at,
            messages=messages,
            agent_goals=goals,
            tool_invocations=tool_invocations,
            related_conversation_ids=row.related_conversation_ids or [],
        )

    @staticmethod
    def _to_conversation_link(row: ConversationLinkRecord) -> ConversationLink:
        return ConversationLink(
            id=row.id,
            left_conversation_id=row.left_conversation_id,
            right_conversation_id=row.right_conversation_id,
            link_kind=row.link_kind,  # type: ignore[arg-type]
            reason=row.reason,
            confidence=row.confidence,
            created_at=row.created_at,
        )

    @staticmethod
    def _to_message(row: ConversationMessageRecord) -> ConversationMessage:
        return ConversationMessage(
            id=row.id,
            role=row.role,
            status=row.status,
            content_type=row.content_type,
            created_at=row.created_at,
            blocks=[MessageBlock(**block) for block in (row.blocks or [])],
            tool_refs=row.tool_refs or [],
            object_refs=row.object_refs or [],
            metadata=row.message_metadata or {},
            stream_id=row.stream_id,
            sequence_max=row.sequence_max,
        )

    @staticmethod
    def _to_goal(row: AgentGoalRecord) -> AgentGoal:
        return AgentGoal(
            id=row.id,
            conversation_id=row.conversation_id,
            project_id=row.project_id,
            us_id=row.us_id,
            goal_template=row.goal_template,
            goal_description=row.goal_description,
            target_refs=row.target_refs or [],
            query_keys=row.query_keys or [],
            planner_kind=row.planner_kind,
            planning_summary=row.planning_summary,
            title=row.title,
            status=row.status,
            summary=row.summary,
            steps=[AgentStep(**step) for step in (row.steps or [])],
            autonomy_level=row.autonomy_level,
            max_steps=row.max_steps,
            max_model_calls=row.max_model_calls,
            max_thinking_tokens=row.max_thinking_tokens,
            max_runtime_seconds=row.max_runtime_seconds,
            max_no_progress_observations=row.max_no_progress_observations,
            steps_completed=row.steps_completed,
            model_calls_used=row.model_calls_used,
            thinking_input_tokens_used=row.thinking_input_tokens_used,
            thinking_output_tokens_used=row.thinking_output_tokens_used,
            thinking_tokens_used=row.thinking_tokens_used,
            no_progress_observations=row.no_progress_observations,
            started_at=row.started_at,
            last_progress_at=row.last_progress_at,
            last_progress_fingerprint=row.last_progress_fingerprint,
            budget_exhausted_reason=row.budget_exhausted_reason,
            pause_reason=row.pause_reason,
            workflow_id=row.workflow_id,
        )

    @staticmethod
    def _to_tool_invocation(row: ToolInvocationRecord) -> ToolInvocation:
        result = ToolResult(**row.result_payload) if row.result_payload else None
        return ToolInvocation(
            id=row.id,
            conversation_id=row.conversation_id,
            tool_id=row.tool_id,
            status=row.status,  # type: ignore[arg-type]
            summary=row.summary,
            initiator_surface=row.initiator_surface,  # type: ignore[arg-type]
            initiator_actor=row.initiator_actor,  # type: ignore[arg-type]
            target_scope=row.target_scope,  # type: ignore[arg-type]
            input_payload=row.input_payload or {},
            result=result,
            idempotency_scope=row.idempotency_scope,
            idempotency_key=row.idempotency_key,
            idempotency_fingerprint=row.idempotency_fingerprint,
            revision=int(row.revision or 0),
        )

    @staticmethod
    def _new_tool_invocation_record(
        invocation: ToolInvocation,
    ) -> ToolInvocationRecord:
        return ToolInvocationRecord(
            id=invocation.id,
            conversation_id=invocation.conversation_id,
            tool_id=invocation.tool_id,
            status=invocation.status,
            summary=invocation.summary,
            initiator_surface=invocation.initiator_surface,
            initiator_actor=invocation.initiator_actor,
            target_scope=invocation.target_scope,
            input_payload=invocation.input_payload,
            result_payload=(
                invocation.result.model_dump() if invocation.result else None
            ),
            idempotency_scope=invocation.idempotency_scope,
            idempotency_key=invocation.idempotency_key,
            idempotency_fingerprint=invocation.idempotency_fingerprint,
            revision=invocation.revision,
        )

    @staticmethod
    def _to_audit_event(row: AuditEventRecord) -> AuditEvent:
        return AuditEvent(
            id=row.id,
            occurred_at=row.occurred_at,
            actor=row.actor,
            actor_kind=row.actor_kind,  # type: ignore[arg-type]
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            status=row.status,  # type: ignore[arg-type]
            summary=row.summary,
            conversation_id=row.conversation_id,
            tool_invocation_id=row.tool_invocation_id,
            agent_goal_id=row.agent_goal_id,
            object_refs=row.object_refs or [],
            evidence_refs=row.evidence_refs or [],
            metadata=row.event_metadata or {},
        )

    @staticmethod
    def _new_audit_event_record(event: AuditEvent) -> AuditEventRecord:
        return AuditEventRecord(
            id=event.id,
            occurred_at=event.occurred_at,
            actor=event.actor,
            actor_kind=event.actor_kind,
            action=event.action,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            status=event.status,
            summary=event.summary,
            conversation_id=event.conversation_id,
            tool_invocation_id=event.tool_invocation_id,
            agent_goal_id=event.agent_goal_id,
            object_refs=event.object_refs,
            evidence_refs=event.evidence_refs,
            event_metadata=event.metadata,
        )

    @classmethod
    def _assert_same_audit_event(
        cls,
        record: AuditEventRecord,
        event: AuditEvent,
    ) -> None:
        if cls._to_audit_event(record) != event:
            raise ValueError(f"audit event {event.id} is immutable")

    @staticmethod
    def _to_swarm(row: AgentSwarmRunRecord, assignments: list[AgentWorkerAssignment]) -> AgentSwarmRun:
        assignments.sort(key=lambda item: item.created_at)
        return AgentSwarmRun(
            id=row.id,
            parent_goal_id=row.parent_goal_id,
            conversation_id=row.conversation_id,
            swarm_kind=row.swarm_kind,  # type: ignore[arg-type]
            status=row.status,  # type: ignore[arg-type]
            max_parallel_agents=row.max_parallel_agents,
            budget_ref=row.budget_ref,
            merge_strategy=row.merge_strategy,
            target_refs=row.target_refs or [],
            result_summary=row.result_summary or "",
            assignments=assignments,
            created_at=row.created_at,
            completed_at=row.completed_at,
        )

    @staticmethod
    def _to_assignment(row: AgentWorkerAssignmentRecord) -> AgentWorkerAssignment:
        return AgentWorkerAssignment(
            id=row.id,
            swarm_run_id=row.swarm_run_id,
            worker_agent_kind=row.worker_agent_kind,  # type: ignore[arg-type]
            target_refs=row.target_refs or [],
            input_context_refs=row.input_context_refs or [],
            status=row.status,  # type: ignore[arg-type]
            agent_goal_id=row.agent_goal_id,
            tool_invocation_refs=row.tool_invocation_refs or [],
            candidate_result_ref=row.candidate_result_ref,
            timeout_seconds=row.timeout_seconds,
            confidence=row.confidence,
            summary=row.summary or "",
            created_at=row.created_at,
            completed_at=row.completed_at,
        )

    @staticmethod
    def _to_agent_memory_item(row: AgentMemoryItemRecord) -> AgentMemoryItem:
        return AgentMemoryItem(
            id=row.id,
            memory_scope=row.memory_scope,  # type: ignore[arg-type]
            owner_ref=row.owner_ref,
            source_refs=row.source_refs or [],
            summary=row.summary,
            object_refs=row.object_refs or [],
            evidence_refs=row.evidence_refs or [],
            status=row.status,  # type: ignore[arg-type]
            expires_at=row.expires_at,
            created_at=row.created_at,
        )

    @staticmethod
    def _to_agent_memory_link(row: AgentMemoryLinkRecord) -> AgentMemoryLink:
        return AgentMemoryLink(
            id=row.id,
            memory_id=row.memory_id,
            target_ref=row.target_ref,
            link_kind=row.link_kind,  # type: ignore[arg-type]
            confidence=row.confidence,
            created_at=row.created_at,
        )

    @staticmethod
    def _to_summary_checkpoint(row: ConversationSummaryCheckpointRecord) -> ConversationSummaryCheckpoint:
        return ConversationSummaryCheckpoint(
            id=row.id,
            conversation_id=row.conversation_id,
            message_range_start=row.message_range_start,
            message_range_end=row.message_range_end,
            summary_text=row.summary_text,
            summary_object_refs=row.summary_object_refs or [],
            summary_token_count=row.summary_token_count,
            created_by=row.created_by,  # type: ignore[arg-type]
            created_at=row.created_at,
        )

    @staticmethod
    def _to_session_knowledge_binding(row: SessionKnowledgeBindingRecord) -> SessionKnowledgeBinding:
        return SessionKnowledgeBinding(
            id=row.id,
            conversation_id=row.conversation_id,
            candidate_object_ref=row.candidate_object_ref,
            scope=row.scope,  # type: ignore[arg-type]
            created_at=row.created_at,
        )
