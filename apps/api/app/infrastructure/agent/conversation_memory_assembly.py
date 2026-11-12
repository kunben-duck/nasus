from ...application.agent.semantic_memory import SemanticConversationMemory
from ..llm.conversation_summary_model import ConversationSummaryModel
from ..llm.conversation_token_budget import memory_enabled
from ..persistence.conversation_memory_repository import ConversationMemoryRepository
from ..persistence.db_models import UserIdentityRecord
from ..persistence.unit_of_work import session_scope
from ...application.platform.actor_context import current_actor


def build_conversation_memory(*, memory, summaries, conversations, repository, llm, settings, secret):
    def require_access(conversation):
        # Re-read identity and conversation authorization, including after a slow model call.
        actor = current_actor()
        if actor:
            with session_scope() as session:
                identity = session.get(UserIdentityRecord, actor.user.id)
                if identity is None or identity.status != "active" or identity.role != actor.user.role:
                    raise PermissionError("Conversation memory identity changed or is unavailable")
        current = conversations.get_conversation(conversation.id)
        return memory.semantic_scope(current)

    async def published(conversation_id, checkpoint_id):
        # The commit already wrote the event atomically; SSE polling delivers it across processes.
        pass

    service = SemanticConversationMemory(jobs=ConversationMemoryRepository(),
        model=ConversationSummaryModel(llm, settings, secret), conversation=conversations.get_conversation,
        checkpoints=repository.load_summary_checkpoints, guard=require_access,
        publish=published)
    if memory_enabled():
        memory.semantic = service
        memory.history_recall = service.recall
        summaries.semantic = service
    return service
