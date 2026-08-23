from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ...application.agent.agent_models import AgentGoal


@dataclass(frozen=True)
class AgentWorkflowRuntimeAdapters:
    get_goal: Callable[[str], AgentGoal]
    accept_remote_goal: Callable[[AgentGoal], None]


__all__ = ["AgentWorkflowRuntimeAdapters"]
