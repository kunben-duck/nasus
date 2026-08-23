from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol

from .tool_models import EventPayload, ToolInvocation


EventStreamKind = Literal["conversation", "goal", "swarm"]


class EventOutboxPort(Protocol):
    def append(self, event: EventPayload) -> EventPayload:
        ...

    def list_after(
        self,
        *,
        stream_kind: EventStreamKind,
        stream_id: str,
        after_event_id: str | None,
        limit: int = 500,
        initial_replay_limit: int = 500,
    ) -> list[EventPayload]:
        ...

    def latest_entity_version(self, *, entity_type: str, entity_id: str) -> int:
        ...


class EventStreamBufferPort(Protocol):
    """Process-local wake-up projection; the outbox remains authoritative."""

    def conversation_queue(self, conversation_id: str) -> asyncio.Queue[EventPayload]:
        ...

    def goal_queue(self, goal_id: str) -> asyncio.Queue[EventPayload]:
        ...

    def swarm_queue(self, swarm_id: str) -> asyncio.Queue[EventPayload]:
        ...

    def remember_entity_version(self, event: EventPayload) -> None:
        ...


class PlatformEventStreamPort(Protocol):
    async def publish_conversation_event(
        self,
        conversation_id: str,
        event: EventPayload,
    ) -> None:
        ...

    async def publish_goal_event(self, goal_id: str, event: EventPayload) -> None:
        ...

    def stream_conversation_events(
        self,
        conversation_id: str,
        last_event_id: str | None = None,
    ) -> AsyncIterator[EventPayload | None]:
        ...

    def stream_goal_events(
        self,
        goal_id: str,
        last_event_id: str | None = None,
    ) -> AsyncIterator[EventPayload | None]:
        ...

    def stream_swarm_events(
        self,
        swarm_id: str,
        last_event_id: str | None = None,
    ) -> AsyncIterator[EventPayload | None]:
        ...

    def latest_entity_version(self, *, entity_type: str, entity_id: str) -> int:
        ...


class PlatformEventEntityReaderPort(Protocol):
    def get_agent_goal(self, goal_id: str) -> Any | None:
        ...

    def get_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        ...

    def get_agent_swarm(self, swarm_id: str) -> Any:
        ...


class ToolInvocationEventProjectionPort(Protocol):
    def persist_and_project(self, invocation: ToolInvocation) -> None:
        ...


__all__ = [
    "EventOutboxPort",
    "EventStreamBufferPort",
    "EventStreamKind",
    "PlatformEventEntityReaderPort",
    "PlatformEventStreamPort",
    "ToolInvocationEventProjectionPort",
]
