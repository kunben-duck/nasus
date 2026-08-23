from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ContextManager

from ...application.platform.event_ports import (
    EventStreamBufferPort,
    PlatformEventEntityReaderPort,
)
from ...application.platform.tool_models import EventPayload, ToolInvocation


@dataclass(frozen=True)
class EventStreamRuntimeSettings:
    poll_seconds: float
    heartbeat_seconds: float


def event_stream_runtime_settings_from_env() -> EventStreamRuntimeSettings:
    return EventStreamRuntimeSettings(
        poll_seconds=max(0.05, float(os.getenv("NASUS_SSE_POLL_SECONDS", "0.5"))),
        heartbeat_seconds=max(
            1.0,
            float(os.getenv("NASUS_SSE_HEARTBEAT_SECONDS", "15")),
        ),
    )


@dataclass(frozen=True)
class EventStreamWakeUpState:
    conversation_queues: dict[str, asyncio.Queue[EventPayload]]
    goal_queues: dict[str, asyncio.Queue[EventPayload]]
    swarm_queues: dict[str, asyncio.Queue[EventPayload]]
    entity_versions: dict[str, int]


class SSEWakeUpBuffer(EventStreamBufferPort):
    """API-local wake-up queues backed by a durable PostgreSQL outbox.

    Queues reduce delivery latency only. They are never replay or ordering
    authorities; consumers always read committed events from the outbox.
    """

    def __init__(
        self,
        facts: EventStreamWakeUpState,
        mutation_guard: Callable[[], ContextManager[Any]],
    ) -> None:
        self._facts = facts
        self._mutation_guard = mutation_guard

    def conversation_queue(self, conversation_id: str) -> asyncio.Queue[EventPayload]:
        return self._queue(self._facts.conversation_queues, conversation_id)

    def goal_queue(self, goal_id: str) -> asyncio.Queue[EventPayload]:
        return self._queue(self._facts.goal_queues, goal_id)

    def swarm_queue(self, swarm_id: str) -> asyncio.Queue[EventPayload]:
        return self._queue(self._facts.swarm_queues, swarm_id)

    def remember_entity_version(self, event: EventPayload) -> None:
        with self._mutation_guard():
            self._facts.entity_versions[
                f"{event.entity_type}:{event.entity_id}"
            ] = event.entity_version

    def _queue(
        self,
        queues: dict[str, asyncio.Queue[EventPayload]],
        stream_id: str,
    ) -> asyncio.Queue[EventPayload]:
        with self._mutation_guard():
            queue = queues.get(stream_id)
            if queue is None:
                queue = asyncio.Queue()
                queues[stream_id] = queue
            return queue


# Compatibility aliases for tests and downstream imports. Production
# composition uses the explicit wake-up names above.
EventStreamProjectionFacts = EventStreamWakeUpState
ProjectedEventStreamBuffer = SSEWakeUpBuffer


@dataclass(frozen=True)
class PlatformEventEntityAdapters:
    get_agent_goal: Callable[[str], Any | None]
    get_tool_invocation: Callable[[str], ToolInvocation]
    get_agent_swarm: Callable[[str], Any]


class CallablePlatformEventEntityReader(PlatformEventEntityReaderPort):
    def __init__(self, adapters: PlatformEventEntityAdapters) -> None:
        self._adapters = adapters

    def get_agent_goal(self, goal_id: str) -> Any | None:
        return self._adapters.get_agent_goal(goal_id)

    def get_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        return self._adapters.get_tool_invocation(invocation_id)

    def get_agent_swarm(self, swarm_id: str) -> Any:
        return self._adapters.get_agent_swarm(swarm_id)


__all__ = [
    "CallablePlatformEventEntityReader",
    "EventStreamProjectionFacts",
    "EventStreamWakeUpState",
    "EventStreamRuntimeSettings",
    "PlatformEventEntityAdapters",
    "ProjectedEventStreamBuffer",
    "SSEWakeUpBuffer",
    "event_stream_runtime_settings_from_env",
]
