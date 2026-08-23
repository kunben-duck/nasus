from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ...application.agent.agent_models import (
    AgentGoal,
    ConversationMessage,
    ConversationSession,
)
from ...application.platform.tool_models import ToolInvocation


@dataclass(frozen=True)
class AgentConversationRuntimeAdapters:
    """Explicit command/query dependencies for main conversation orchestration."""

    get_conversation: Callable[[str], ConversationSession]
    append_message: Callable[..., Awaitable[ConversationMessage]]
    plan_message: Callable[..., Awaitable[Any]]
    fallback_text: Callable[[ConversationSession], str]
    create_tool_invocation: Callable[[Any], Awaitable[ToolInvocation]]
    start_goal_from_proposal: Callable[[str, Any], Awaitable[AgentGoal]]
    is_confirmation_message: Callable[[str], bool]
    list_tool_invocations: Callable[..., list[ToolInvocation]]
    is_paused_goal: Callable[[str], bool]
    resume_goal: Callable[[str], Awaitable[AgentGoal]]
    get_tool_invocation: Callable[[str], ToolInvocation]
    confirm_tool_invocation: Callable[[str], Awaitable[ToolInvocation]]
    active_goal_for_conversation: Callable[[str], AgentGoal | None]
    project_goal: Callable[[AgentGoal], None]
    record_source_binding_received: Callable[[AgentGoal, list[str]], None]


__all__ = ["AgentConversationRuntimeAdapters"]
