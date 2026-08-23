from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from typing import Any

from ...application.agent.agent_models import (
    AgentGoal,
    AgentGoalCreateRequest,
    ConversationMessage,
    ConversationSession,
)


@dataclass(frozen=True)
class AgentGoalProjectionState:
    conversations: MutableMapping[str, ConversationSession]


@dataclass(frozen=True)
class AgentGoalLifecycleState:
    goals: MutableMapping[str, AgentGoal]
    conversations: MutableMapping[str, ConversationSession]


@dataclass(frozen=True)
class AgentGoalProjectionPersistenceAdapters:
    upsert_goal: Callable[[AgentGoal], None]
    upsert_conversation: Callable[[ConversationSession], None]


@dataclass(frozen=True)
class AgentGoalLifecycleAdapters:
    project_goal: Callable[[AgentGoal], None]
    record_goal_audit_event: Callable[..., None]
    append_text_message: Callable[..., Awaitable[ConversationMessage]]
    push_goal_event: Callable[..., Awaitable[Any]]
    push_conversation_event: Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class AgentLoopRuntimeAdapters:
    get_conversation: Callable[[str], ConversationSession]
    create_goal: Callable[[AgentGoalCreateRequest], AgentGoal]
    get_goal: Callable[[str], AgentGoal]


__all__ = [
    "AgentGoalLifecycleAdapters",
    "AgentGoalLifecycleState",
    "AgentGoalProjectionPersistenceAdapters",
    "AgentGoalProjectionState",
    "AgentLoopRuntimeAdapters",
]
