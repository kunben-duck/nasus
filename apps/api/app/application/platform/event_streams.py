from __future__ import annotations

import asyncio
from time import monotonic

from .event_ports import EventOutboxPort, EventStreamBufferPort, EventStreamKind
from .tool_models import EventPayload


class PlatformEventStreamApplicationService:
    """Persists events before fan-out and replays them across API instances."""

    def __init__(
        self,
        outbox: EventOutboxPort,
        buffer: EventStreamBufferPort,
        *,
        poll_seconds: float,
        heartbeat_seconds: float,
    ) -> None:
        self._outbox = outbox
        self._buffer = buffer
        self._poll_seconds = max(0.05, poll_seconds)
        self._heartbeat_seconds = max(1.0, heartbeat_seconds)

    def conversation_queue(self, conversation_id: str) -> asyncio.Queue[EventPayload]:
        return self._buffer.conversation_queue(conversation_id)

    def goal_queue(self, goal_id: str) -> asyncio.Queue[EventPayload]:
        return self._buffer.goal_queue(goal_id)

    def swarm_queue(self, swarm_id: str) -> asyncio.Queue[EventPayload]:
        return self._buffer.swarm_queue(swarm_id)

    async def publish_conversation_event(self, conversation_id: str, event: EventPayload) -> None:
        await asyncio.to_thread(self._outbox.append, event)
        self._buffer.remember_entity_version(event)
        await self.conversation_queue(conversation_id).put(event)
        if event.agent_goal_id:
            await self.goal_queue(event.agent_goal_id).put(event)
        if event.swarm_run_id:
            await self.swarm_queue(event.swarm_run_id).put(event)

    async def publish_goal_event(self, goal_id: str, event: EventPayload) -> None:
        await asyncio.to_thread(self._outbox.append, event)
        self._buffer.remember_entity_version(event)
        await self.goal_queue(goal_id).put(event)
        if event.conversation_id:
            await self.conversation_queue(event.conversation_id).put(event)
        if event.swarm_run_id:
            await self.swarm_queue(event.swarm_run_id).put(event)

    async def stream_conversation_events(self, conversation_id: str, last_event_id: str | None = None):
        async for event in self._stream(
            stream_kind="conversation",
            stream_id=conversation_id,
            queue=self.conversation_queue(conversation_id),
            last_event_id=last_event_id,
        ):
            yield event

    async def stream_goal_events(self, goal_id: str, last_event_id: str | None = None):
        async for event in self._stream(
            stream_kind="goal",
            stream_id=goal_id,
            queue=self.goal_queue(goal_id),
            last_event_id=last_event_id,
        ):
            yield event

    async def stream_swarm_events(self, swarm_id: str, last_event_id: str | None = None):
        async for event in self._stream(
            stream_kind="swarm",
            stream_id=swarm_id,
            queue=self.swarm_queue(swarm_id),
            last_event_id=last_event_id,
        ):
            yield event

    def latest_entity_version(self, *, entity_type: str, entity_id: str) -> int:
        return self._outbox.latest_entity_version(
            entity_type=entity_type,
            entity_id=entity_id,
        )

    async def _stream(
        self,
        *,
        stream_kind: EventStreamKind,
        stream_id: str,
        queue: asyncio.Queue[EventPayload],
        last_event_id: str | None,
    ):
        cursor = last_event_id
        last_activity = monotonic()
        while True:
            events = await asyncio.to_thread(
                self._outbox.list_after,
                stream_kind=stream_kind,
                stream_id=stream_id,
                after_event_id=cursor,
            )
            if events:
                for event in events:
                    cursor = event.event_id
                    last_activity = monotonic()
                    yield event
                continue

            try:
                await asyncio.wait_for(queue.get(), timeout=self._poll_seconds)
                while not queue.empty():
                    queue.get_nowait()
            except asyncio.TimeoutError:
                pass

            if monotonic() - last_activity >= self._heartbeat_seconds:
                last_activity = monotonic()
                yield None


__all__ = ["PlatformEventStreamApplicationService"]
