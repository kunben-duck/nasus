from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from ...application.agent.agent_models import (
    AgentGoal,
    AgentMemoryItem,
    ConversationSession,
    ConversationSummaryCheckpoint,
)
from ...application.platform.tool_models import ToolInvocation, ToolInvocationRequest
from ...domain.agent.memory import AgentMemoryContext


@dataclass(frozen=True)
class AgentGraphLookupAdapters:
    get_goal: Callable[[str], AgentGoal]
    get_conversation: Callable[[str], ConversationSession]


@dataclass(frozen=True)
class AgentGraphToolRuntimeAdapters:
    create_tool_invocation: Callable[[ToolInvocationRequest], Awaitable[ToolInvocation]]
    confirm_tool_invocation: Callable[[str], Awaitable[ToolInvocation]]
    get_tool_invocation: Callable[[str], ToolInvocation]
    available_tool_ids: Callable[[], Iterable[str]]


@dataclass(frozen=True)
class AgentGraphMemoryAdapters:
    create_summary_checkpoint: Callable[..., Awaitable[ConversationSummaryCheckpoint]]
    record_memory_item: Callable[..., AgentMemoryItem]
    build_memory_context: Callable[[ConversationSession], Awaitable[AgentMemoryContext]]


__all__ = [
    "AgentGraphLookupAdapters",
    "AgentGraphMemoryAdapters",
    "AgentGraphToolRuntimeAdapters",
]
