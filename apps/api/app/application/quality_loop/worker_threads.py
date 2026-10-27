"""Join owned synchronous work before reporting asynchronous cancellation."""
import asyncio


async def run_worker_thread(operation, *, on_cancel=None):
    task = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            if on_cancel is not None:
                on_cancel()
        finally:
            # Repeated cancellation cannot orphan a DB/Runner thread either.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if task.done() and not task.cancelled():
                task.exception()
        raise
