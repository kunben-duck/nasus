from __future__ import annotations

from collections.abc import Callable, MutableMapping
from dataclasses import dataclass

from ...application.agent.agent_models import ConversationLink, ConversationSession


@dataclass(frozen=True)
class AgentConversationManagementProjectionState:
    conversations: MutableMapping[str, ConversationSession]
    conversation_index: MutableMapping[tuple[str, str, str], str]
    conversation_links: MutableMapping[str, ConversationLink]


@dataclass(frozen=True)
class AgentConversationManagementPersistenceAdapters:
    upsert_conversation: Callable[[ConversationSession], None]
    upsert_conversation_link: Callable[[ConversationLink], None]


@dataclass(frozen=True)
class AgentConversationManagementRuntimeAdapters:
    resolve_scope: Callable[..., tuple[str | None, str | None, str | None]]
    current_user_id: Callable[[], str]
    require_project_access: Callable[[str], None]
    require_conversation_access: Callable[[ConversationSession], None]
    can_access_conversation: Callable[[ConversationSession], bool]


__all__ = [
    "AgentConversationManagementPersistenceAdapters",
    "AgentConversationManagementProjectionState",
    "AgentConversationManagementRuntimeAdapters",
]
