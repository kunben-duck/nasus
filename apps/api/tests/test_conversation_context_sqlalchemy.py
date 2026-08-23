from __future__ import annotations

from uuid import uuid4

from sqlalchemy import delete

from apps.api.app.application.agent.agent_models import (
    ConversationSession,
    ConversationSummaryCheckpoint,
    SessionKnowledgeBinding,
)
from apps.api.app.infrastructure.agent.sqlalchemy_application_ports import (
    SQLAlchemyAgentMemoryState,
    SQLAlchemyConversationSummaryState,
)
from apps.api.app.infrastructure.persistence.conversation_repository import (
    ConversationRepository,
)
from apps.api.app.infrastructure.persistence.database import init_database
from apps.api.app.infrastructure.persistence.db_models import (
    ConversationRecord,
    ConversationSummaryCheckpointRecord,
    SessionKnowledgeBindingRecord,
)
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope

def _cleanup(conversation_id: str, checkpoint_id: str, binding_id: str) -> None:
    with session_scope() as session:
        session.execute(
            delete(ConversationSummaryCheckpointRecord).where(
                ConversationSummaryCheckpointRecord.id == checkpoint_id
            )
        )
        session.execute(
            delete(SessionKnowledgeBindingRecord).where(
                SessionKnowledgeBindingRecord.id == binding_id
            )
        )
        session.execute(
            delete(ConversationRecord).where(ConversationRecord.id == conversation_id)
        )


def test_summary_checkpoint_is_visible_across_repository_instances_without_projection() -> None:
    init_database()
    suffix = uuid4().hex[:10]
    conversation_id = f"conversation_context_{suffix}"
    checkpoint_id = f"checkpoint_context_{suffix}"
    binding_id = f"binding_context_{suffix}"
    writer = ConversationRepository()
    conversation = ConversationSession(
        id=conversation_id,
        session_id=f"session_{suffix}",
        title="Durable conversation context",
        space_type="documentation",
        space_id=f"space_{suffix}",
        initiator_id=f"user_{suffix}",
        status="active",
    )
    checkpoint = ConversationSummaryCheckpoint(
        id=checkpoint_id,
        conversation_id=conversation_id,
        summary_text="The checkpoint is durable across application processes.",
        summary_token_count=8,
        created_by="system",
        created_at="2026-08-09T00:00:00+00:00",
    )
    state = SQLAlchemyConversationSummaryState(writer)
    _cleanup(conversation_id, checkpoint_id, binding_id)

    try:
        writer.upsert_conversation(conversation)
        state.persist_summary_checkpoint(conversation, checkpoint)

        reader = ConversationRepository()
        assert checkpoint in reader.load_summary_checkpoints()
        assert reader.get_conversation(conversation_id) is not None
    finally:
        _cleanup(conversation_id, checkpoint_id, binding_id)


def test_session_knowledge_binding_is_read_from_postgresql_by_agent_memory_state() -> None:
    init_database()
    suffix = uuid4().hex[:10]
    conversation_id = f"conversation_binding_{suffix}"
    checkpoint_id = f"checkpoint_binding_{suffix}"
    binding_id = f"binding_context_{suffix}"
    binding = SessionKnowledgeBinding(
        id=binding_id,
        conversation_id=conversation_id,
        candidate_object_ref=f"candidate_knowledge:{suffix}",
        created_at="2026-08-09T00:00:00+00:00",
    )
    _cleanup(conversation_id, checkpoint_id, binding_id)

    try:
        ConversationRepository().upsert_session_knowledge_binding(binding)
        reader_state = SQLAlchemyAgentMemoryState(
            conversations=ConversationRepository(),
            projects=object(),  # type: ignore[arg-type]
            quality_loop=object(),  # type: ignore[arg-type]
            system_image=object(),  # type: ignore[arg-type]
            tools=(),
            push_event=None,
        )

        assert reader_state.session_candidate_refs(conversation_id) == (
            binding.candidate_object_ref,
        )
    finally:
        _cleanup(conversation_id, checkpoint_id, binding_id)
