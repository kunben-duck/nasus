from __future__ import annotations

from uuid import uuid4

from sqlalchemy import delete

from apps.api.app.application.agent.agent_models import AgentGoal, ConversationSession
from apps.api.app.infrastructure.agent.sqlalchemy_application_ports import (
    SQLAlchemyAgentGoalProjectionState,
)
from apps.api.app.infrastructure.persistence.conversation_repository import (
    ConversationRepository,
)
from apps.api.app.infrastructure.persistence.database import init_database
from apps.api.app.infrastructure.persistence.db_models import AgentGoalRecord, ConversationRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope

def _cleanup(conversation_id: str, goal_id: str) -> None:
    with session_scope() as session:
        session.execute(delete(AgentGoalRecord).where(AgentGoalRecord.id == goal_id))
        session.execute(
            delete(ConversationRecord).where(ConversationRecord.id == conversation_id)
        )


def test_agent_goal_is_visible_across_repository_instances_without_goal_projection() -> None:
    init_database()
    suffix = uuid4().hex[:10]
    conversation_id = f"conversation_goal_{suffix}"
    goal_id = f"goal_sql_{suffix}"
    conversation = ConversationSession(
        id=conversation_id,
        session_id=f"session_goal_{suffix}",
        title="Durable AgentGoal",
        space_type="build",
        space_id=f"build_{suffix}",
        initiator_id=f"user_{suffix}",
        status="active",
    )
    goal = AgentGoal(
        id=goal_id,
        conversation_id=conversation_id,
        title="Persist goal through Agent application port",
        status="pending",
        summary="The goal must be visible to API and Temporal processes.",
        steps=[],
    )
    conversation.agent_goals = [goal]
    writer = ConversationRepository()
    state = SQLAlchemyAgentGoalProjectionState(writer)
    _cleanup(conversation_id, goal_id)

    try:
        writer.upsert_conversation(conversation)
        state.persist_goal_projection(conversation, goal)

        reader = ConversationRepository()
        assert reader.get_agent_goal(goal_id) == goal
        restored = reader.get_conversation(conversation_id)
        assert restored is not None
        assert restored.agent_goals == [goal]
    finally:
        _cleanup(conversation_id, goal_id)
