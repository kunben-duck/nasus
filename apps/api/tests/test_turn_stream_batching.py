import asyncio
from contextvars import ContextVar
from types import SimpleNamespace

import pytest

from apps.api.app.application.agent.stream_batching import stream_with_idle_flush
from apps.api.app.application.agent.agent_models import ConversationTurn
from apps.api.app.application.agent.turns import (
    ConversationTurnApplicationService,
    ConversationTurnExecutionRequest,
)


def test_idle_flush_does_not_cancel_slow_source_or_change_events():
    async def run():
        ticks, closed = [], []
        release = asyncio.Event()
        context = ContextVar("protocol_source_context", default=None)

        async def source():
            token = context.set("producer")
            try:
                yield {"kind": "delta", "delta": "first"}
                await release.wait()
                assert context.get() == "producer"
                yield {"kind": "completed"}
            finally:
                context.reset(token)
                closed.append(True)

        async def flush():
            ticks.append(True)
            if len(ticks) == 2:
                assert not closed
                release.set()

        events = [event async for event in stream_with_idle_flush(source(), flush, interval=0.01)]
        assert events == [{"kind": "delta", "delta": "first"}, {"kind": "completed"}]
        assert len(ticks) == 2 and closed == [True]

    asyncio.run(asyncio.wait_for(run(), timeout=1))


@pytest.mark.parametrize("failure", [RuntimeError("provider disconnected"), asyncio.CancelledError()])
def test_provider_failure_is_propagated_and_source_closed(failure):
    async def run():
        closed = []

        async def source():
            try:
                yield {"kind": "delta", "delta": "partial"}
                raise failure
            finally:
                closed.append(True)

        async def flush():
            pass

        stream = stream_with_idle_flush(source(), flush, interval=0.01)
        assert await stream.__anext__() == {"kind": "delta", "delta": "partial"}
        with pytest.raises(type(failure)):
            await stream.__anext__()
        assert closed == [True]

    asyncio.run(asyncio.wait_for(run(), timeout=1))


def test_consumer_close_cancels_source_with_bounded_backpressure():
    async def run():
        produced, closed = [], []

        async def source():
            try:
                for index in range(1000):
                    produced.append(index)
                    yield {"kind": "delta", "delta": str(index)}
            finally:
                closed.append(True)

        async def flush():
            pass

        stream = stream_with_idle_flush(source(), flush, interval=0.01)
        assert await stream.__anext__() == {"kind": "delta", "delta": "0"}
        await asyncio.sleep(0.02)
        assert len(produced) <= 3
        await stream.aclose()
        assert closed == [True]

    asyncio.run(asyncio.wait_for(run(), timeout=1))


def test_source_cleanup_failure_cannot_be_reported_as_completion():
    class Source:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def aclose(self):
            raise RuntimeError("source cleanup failed")

    async def run():
        async def flush():
            pass

        with pytest.raises(RuntimeError, match="source cleanup failed"):
            async for _ in stream_with_idle_flush(Source(), flush):
                raise AssertionError("empty source cannot emit a token")

    asyncio.run(asyncio.wait_for(run(), timeout=1))


@pytest.mark.parametrize("committed", [False, True])
@pytest.mark.parametrize("initial_sequence", [0, 7])
@pytest.mark.parametrize("failure_type", [asyncio.CancelledError, RuntimeError])
def test_interrupted_flush_reuses_sequence_until_persistence_acknowledges(
    committed, initial_sequence, failure_type,
):
    async def run():
        turn = ConversationTurn(
            id="turn-protocol", conversation_id="conversation-protocol",
            user_message_id="user-protocol", assistant_message_id="assistant-protocol",
            idempotency_key="protocol", created_at="2026-10-07T00:00:00Z",
            updated_at="2026-10-07T00:00:00Z",
        )
        message = SimpleNamespace(
            id=turn.assistant_message_id, stream_id="stream-protocol",
            sequence_max=initial_sequence, status="streaming", text="Existing: ",
        )
        attempts, terminal_events, closed = [], [], []
        delta = "Partial answer: \u4f60\u597d"

        class Messages:
            def get_message(self, conversation_id, message_id):
                assert (conversation_id, message_id) == (turn.conversation_id, message.id)
                return message

            async def append_stream_delta(self, conversation_id, message_id, *, stream_id, sequence, delta):
                assert stream_id == message.stream_id
                attempts.append(sequence)
                first = len(attempts) == 1
                if first and not committed:
                    raise failure_type("interrupted before commit")
                if sequence > message.sequence_max:
                    message.text += delta
                    message.sequence_max = sequence
                if first:
                    raise failure_type("interrupted after commit before acknowledgement")
                return message

            async def finish_streaming_message(self, conversation_id, message_id, *, stream_id, status, **kwargs):
                assert stream_id == message.stream_id
                message.status = status
                return message

        async def publish(conversation_id, turn_id, name, payload):
            terminal_events.append(name)

        async def events(request):
            try:
                yield {"kind": "started"}
                yield {"kind": "delta", "delta": delta}
                yield {"kind": "completed"}
            finally:
                closed.append(True)

        service = ConversationTurnApplicationService(
            SimpleNamespace(get=lambda ident: turn, upsert=lambda value: None),
            Messages(), SimpleNamespace(publish_turn_event=publish),
            SimpleNamespace(astream=events),
        )
        result = await service.execute_turn(ConversationTurnExecutionRequest(
            turn.id, turn.conversation_id, "protocol input", None,
        ))
        status = "interrupted" if failure_type is asyncio.CancelledError else "failed"
        assert result.status == message.status == status
        assert attempts == [initial_sequence + 1, initial_sequence + 1]
        assert message.sequence_max == initial_sequence + 1
        assert message.text == "Existing: " + delta
        assert terminal_events == ["conversation.turn." + status]
        assert closed == [True]

    asyncio.run(asyncio.wait_for(run(), timeout=1))
