from __future__ import annotations

from uuid import uuid4

from sqlalchemy import delete

from apps.api.app.application.agent.agent_models import ConversationSession
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.platform.tool_projection import (
    ToolInvocationProjectionApplicationService,
)
from apps.api.app.infrastructure.persistence.conversation_repository import (
    ConversationRepository,
)
from apps.api.app.infrastructure.persistence.database import init_database
from apps.api.app.infrastructure.persistence.db_models import (
    ConversationRecord,
    ToolInvocationRecord,
)
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.platform.tool_projection import (
    SQLAlchemyToolInvocationProjectionState,
)


def _cleanup(conversation_id: str, invocation_id: str) -> None:
    with session_scope() as session:
        session.execute(
            delete(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
        )
        session.execute(
            delete(ConversationRecord).where(ConversationRecord.id == conversation_id)
        )


def test_sql_projection_is_visible_to_other_repository_instances() -> None:
    init_database()
    suffix = uuid4().hex[:10]
    conversation_id = f"conversation_projection_{suffix}"
    invocation_id = f"tool_projection_{suffix}"
    writer_repository = ConversationRepository()
    reader_repository = ConversationRepository()
    projection = ToolInvocationProjectionApplicationService(
        SQLAlchemyToolInvocationProjectionState(writer_repository)
    )
    local_conversation = ConversationSession(
        id=conversation_id,
        session_id=f"session_projection_{suffix}",
        title="SQL projection",
        space_type="project",
        space_id=f"project_projection_{suffix}",
        project_id=f"project_projection_{suffix}",
    )
    invocation = ToolInvocation(
        id=invocation_id,
        conversation_id=conversation_id,
        tool_id="run.progress.get",
        status="running",
        summary="Running",
        revision=1,
    )
    _cleanup(conversation_id, invocation_id)

    try:
        writer_repository.upsert_conversation(local_conversation)
        projection.persist_and_project(invocation)

        persisted = reader_repository.get_tool_invocation(invocation_id)
        conversation_read_model = reader_repository.get_conversation(conversation_id)

        assert persisted == invocation
        assert conversation_read_model is not None
        assert conversation_read_model.tool_invocations == [invocation]
        assert local_conversation.tool_invocations == []

        invocation.status = "completed"
        invocation.summary = "Completed"
        invocation.revision = 2
        invocation.result = ToolResult(
            invocation_id=invocation_id,
            status="completed",
            summary="Completed",
        )
        projection.upsert_in_conversation(invocation)

        refreshed = ConversationRepository().get_conversation(conversation_id)
        assert refreshed is not None
        assert len(refreshed.tool_invocations) == 1
        assert refreshed.tool_invocations[0].status == "completed"
        assert refreshed.tool_invocations[0].result == invocation.result
    finally:
        _cleanup(conversation_id, invocation_id)
