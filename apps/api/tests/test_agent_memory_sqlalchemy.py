from __future__ import annotations

from uuid import uuid4

from sqlalchemy import delete

from apps.api.app.application.agent.agent_models import AgentMemoryItem, AgentMemoryLink
from apps.api.app.infrastructure.agent.sqlalchemy_application_ports import (
    SQLAlchemyAgentMemoryState,
)
from apps.api.app.infrastructure.persistence.conversation_repository import (
    ConversationRepository,
)
from apps.api.app.infrastructure.persistence.database import init_database
from apps.api.app.infrastructure.persistence.db_models import (
    AgentMemoryItemRecord,
    AgentMemoryLinkRecord,
)
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


def _cleanup(item_id: str, link_id: str) -> None:
    with session_scope() as session:
        session.execute(
            delete(AgentMemoryLinkRecord).where(AgentMemoryLinkRecord.id == link_id)
        )
        session.execute(
            delete(AgentMemoryItemRecord).where(AgentMemoryItemRecord.id == item_id)
        )


def test_sql_agent_memory_is_visible_across_repository_instances_without_projection() -> None:
    init_database()
    suffix = uuid4().hex[:10]
    item_id = f"memory_sql_{suffix}"
    link_id = f"memory_link_sql_{suffix}"
    writer_repository = ConversationRepository()
    state = SQLAlchemyAgentMemoryState(
        conversations=writer_repository,
        projects=object(),  # type: ignore[arg-type]
        quality_loop=object(),  # type: ignore[arg-type]
        system_image=object(),  # type: ignore[arg-type]
        tools=(),
        push_event=None,
    )
    item = AgentMemoryItem(
        id=item_id,
        memory_scope="project_long_term",
        owner_ref=f"project:{suffix}",
        source_refs=[f"agent_goal:{suffix}"],
        summary="Persisted Agent memory",
        object_refs=[f"context_object:{suffix}"],
        evidence_refs=[f"evidence:{suffix}"],
        created_at="2026-08-09T00:00:00+00:00",
    )
    link = AgentMemoryLink(
        id=link_id,
        memory_id=item_id,
        target_ref=f"project:{suffix}",
        link_kind="belongs_to",
        confidence=1,
        created_at="2026-08-09T00:00:00+00:00",
    )
    _cleanup(item_id, link_id)

    try:
        state.persist_memory_item(item)
        state.persist_memory_link(link)

        reader_repository = ConversationRepository()
        assert item in state.list_memory_items()
        assert item in reader_repository.load_agent_memory_items()
        assert link in reader_repository.load_agent_memory_links()
    finally:
        _cleanup(item_id, link_id)
