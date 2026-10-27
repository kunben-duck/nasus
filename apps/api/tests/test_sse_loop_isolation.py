from __future__ import annotations

import asyncio
from threading import RLock

import pytest

from apps.api.app.application.platform.event_streams import PlatformEventStreamApplicationService
from apps.api.app.application.platform.tool_models import EventPayload
from apps.api.app.infrastructure.platform.event_runtime import EventStreamWakeUpState, SSEWakeUpBuffer


def buffer():
    lock = RLock()
    return SSEWakeUpBuffer(EventStreamWakeUpState({}, {}, {}, {}), lambda: lock)


@pytest.mark.parametrize("kind", ["conversation", "goal", "swarm"])
def test_wakeup_queue_never_reuses_another_event_loops_waiters(kind):
    wakeups = buffer()
    get_queue = getattr(wakeups, f"{kind}_queue")

    async def bind_queue():
        queue = get_queue("stream")
        assert get_queue("stream") is queue
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=0.01)
        return queue

    first = asyncio.run(bind_queue())
    second = asyncio.run(bind_queue())
    assert first is not second


class ThreadSafeOutbox:
    def __init__(self):
        self.events = []
        self.lock = RLock()

    def append(self, event):
        with self.lock:
            event.entity_version = len(self.events) + 1
            self.events.append(event)
        return event

    def list_after(self, *, stream_kind, stream_id, after_event_id):
        field = {"conversation": "conversation_id", "goal": "agent_goal_id", "swarm": "swarm_run_id"}[stream_kind]
        with self.lock:
            events = list(self.events)
        start = next((i + 1 for i, event in enumerate(events) if event.event_id == after_event_id), 0)
        return [event for event in events[start:] if getattr(event, field) == stream_id]

    def latest_entity_version(self, **_kwargs):
        with self.lock:
            return len(self.events)


@pytest.mark.parametrize("kind", ["conversation", "goal", "swarm"])
def test_background_turn_loop_cannot_break_api_stream_or_replace_durable_replay(kind):
    wakeups, outbox = buffer(), ThreadSafeOutbox()
    streams = PlatformEventStreamApplicationService(outbox, wakeups, poll_seconds=0.05, heartbeat_seconds=1)
    event = EventPayload(event_id="event_loop_isolation", event_type="tool.invocation.updated",
        occurred_at="2026-10-07T00:00:00+00:00", correlation_id="tool_loop_isolation",
        conversation_id="conversation", agent_goal_id="goal", swarm_run_id="swarm",
        entity_type="tool_invocation", entity_id="tool_loop_isolation", entity_version=0,
        mutation_kind="replace", patch={"status": "completed"})

    async def receive():
        get_queue = getattr(wakeups, f"{kind}_queue")
        api_queue = get_queue(kind)
        iterator = getattr(streams, f"stream_{kind}_events")(kind)
        pending = asyncio.create_task(iterator.__anext__())

        async def wait_for_reader():
            while not api_queue._getters:
                await asyncio.sleep(0)

        async def publish():
            assert get_queue(kind) is not api_queue
            await streams.publish_conversation_event("conversation", event)

        try:
            await asyncio.wait_for(wait_for_reader(), timeout=1)
            await asyncio.to_thread(lambda: asyncio.run(publish()))
            assert await asyncio.wait_for(pending, timeout=1) == event
            assert get_queue(kind) is api_queue and api_queue.empty()
            assert outbox.events == [event] and event.entity_version == 1
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            await iterator.aclose()

    asyncio.run(receive())
