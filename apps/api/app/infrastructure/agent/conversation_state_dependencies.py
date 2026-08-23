from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from typing import Any

from ...application.agent.agent_models import (
    AgentGoal,
    AgentMemoryItem,
    ConversationMessage,
    ConversationSession,
    ConversationSummaryCheckpoint,
)
from ...application.platform.tool_models import AuditEvent, ToolInvocation


@dataclass(frozen=True)
class AgentConversationProjectionState:
    conversations: MutableMapping[str, ConversationSession]
    summary_checkpoints: MutableMapping[str, ConversationSummaryCheckpoint]


@dataclass(frozen=True)
class AgentConversationPersistenceAdapters:
    append_message: Callable[[str, ConversationMessage], None]
    upsert_conversation: Callable[[ConversationSession], None]
    upsert_summary_checkpoint: Callable[[ConversationSummaryCheckpoint], None]


@dataclass(frozen=True)
class AgentConversationCheckpointAdapters:
    maybe_create_summary_checkpoint: Callable[
        [ConversationSession],
        Awaitable[ConversationSummaryCheckpoint | None],
    ]


@dataclass(frozen=True)
class AgentConversationEventAdapters:
    push_event: Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class AgentGoalExplanationAdapters:
    get_goal: Callable[[str], AgentGoal]
    get_checkpoint: Callable[[str], Any]
    get_tool_invocation: Callable[[str], ToolInvocation]
    list_tool_invocations: Callable[..., list[ToolInvocation]]
    list_agent_memory_items: Callable[..., list[AgentMemoryItem]]
    list_audit_events: Callable[..., list[AuditEvent]]


__all__ = [
    "AgentConversationCheckpointAdapters",
    "AgentConversationEventAdapters",
    "AgentConversationPersistenceAdapters",
    "AgentConversationProjectionState",
    "AgentGoalExplanationAdapters",
]
