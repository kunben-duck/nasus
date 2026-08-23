from __future__ import annotations

from uuid import uuid4

from sqlalchemy import delete

from apps.api.app.application.agent.agent_models import (
    AgentSwarmRun,
    AgentWorkerAssignment,
)
from apps.api.app.infrastructure.agent.sqlalchemy_application_ports import (
    SQLAlchemyAgentSwarmState,
)
from apps.api.app.infrastructure.persistence.conversation_repository import (
    ConversationRepository,
)
from apps.api.app.infrastructure.persistence.database import init_database
from apps.api.app.infrastructure.persistence.db_models import (
    AgentSwarmRunRecord,
    AgentWorkerAssignmentRecord,
)
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


def _cleanup(swarm_id: str, assignment_id: str) -> None:
    with session_scope() as session:
        session.execute(
            delete(AgentWorkerAssignmentRecord).where(
                AgentWorkerAssignmentRecord.id == assignment_id
            )
        )
        session.execute(
            delete(AgentSwarmRunRecord).where(AgentSwarmRunRecord.id == swarm_id)
        )


def test_sql_agent_swarm_is_visible_across_repository_instances_without_projection() -> None:
    init_database()
    suffix = uuid4().hex[:10]
    swarm_id = f"swarm_sql_{suffix}"
    assignment_id = f"assignment_sql_{suffix}"
    writer_repository = ConversationRepository()
    state = SQLAlchemyAgentSwarmState(
        writer_repository,
        push_event=None,
    )
    assignment = AgentWorkerAssignment(
        id=assignment_id,
        swarm_run_id=swarm_id,
        worker_agent_kind="context",
        target_refs=[f"raw_asset:{suffix}"],
        input_context_refs=[f"object://source/{suffix}"],
        status="completed",
        candidate_result_ref=f"candidate:{suffix}",
        confidence=0.91,
        summary="Source analyzed",
        created_at="2026-08-09T00:00:00+00:00",
        completed_at="2026-08-09T00:00:01+00:00",
    )
    swarm = AgentSwarmRun(
        id=swarm_id,
        parent_goal_id=f"goal:{suffix}",
        conversation_id=f"conversation:{suffix}",
        swarm_kind="ingestion",
        status="completed",
        target_refs=[f"project:{suffix}"],
        result_summary="Merged one candidate",
        assignments=[assignment],
        created_at="2026-08-09T00:00:00+00:00",
        completed_at="2026-08-09T00:00:01+00:00",
    )
    _cleanup(swarm_id, assignment_id)

    try:
        state.persist_swarm(swarm)

        persisted = ConversationRepository().get_agent_swarm(swarm_id)
        assert persisted == swarm
        assert state.get_swarm(swarm_id) == swarm
    finally:
        _cleanup(swarm_id, assignment_id)
