from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Awaitable, Callable


async def stream_with_idle_flush(
    source: AsyncIterator[dict[str, Any]],
    on_idle: Callable[[], Awaitable[None]],
    *,
    interval: float = 0.05,
) -> AsyncIterator[dict[str, Any]]:
    """Flush buffered tokens without cancelling a slow provider's pending read."""
    if interval <= 0:
        raise ValueError("flush interval must be positive")
    queue: asyncio.Queue[tuple[dict[str, Any] | None, Exception | None]] = asyncio.Queue(maxsize=1)

    async def produce() -> None:
        try:
            # One producer task preserves graph/provider context-manager ownership.
            async for event in source:
                await queue.put((event, None))
        except Exception as error:
            await queue.put((None, error))
        else:
            await queue.put((None, None))
        finally:
            close = getattr(source, "aclose", None)
            if close is not None:
                await close()

    producer = asyncio.create_task(produce())
    try:
        while True:
            try:
                event, error = await asyncio.wait_for(queue.get(), timeout=interval)
            except asyncio.TimeoutError:
                if producer.done():
                    await producer
                await on_idle()
                continue
            if error is not None:
                raise error
            if event is None:
                await producer
                return
            yield event
    finally:
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
