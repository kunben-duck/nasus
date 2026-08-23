from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from typing import Any

from ...application.agent.agent_models import AgentSwarmRun


@dataclass(frozen=True)
class AgentSwarmProjectionState:
    swarms: MutableMapping[str, AgentSwarmRun]


@dataclass(frozen=True)
class AgentSwarmPersistenceAdapters:
    upsert_swarm: Callable[[AgentSwarmRun], None]


@dataclass(frozen=True)
class AgentSwarmEventAdapters:
    push_event: Callable[..., Awaitable[Any]]


__all__ = [
    "AgentSwarmEventAdapters",
    "AgentSwarmPersistenceAdapters",
    "AgentSwarmProjectionState",
]
