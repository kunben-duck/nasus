"""Await owned build cleanup before acknowledging asynchronous cancellation."""
import asyncio
from threading import Event
from typing import Callable

from .native_build_ports import NativeBuildPort
from ...domain.quality_loop.native_build import NativeBuildRequest


class NativeBuildInterrupted(RuntimeError):
    pass


async def execute_native_build(builder: NativeBuildPort, request: NativeBuildRequest, *, require_work: Callable[[], None]):
    stopped = Event()

    def current():
        if stopped.is_set():
            raise NativeBuildInterrupted("native build cancellation requested")
        require_work()
        if stopped.is_set():
            raise NativeBuildInterrupted("native build cancellation requested")

    work = asyncio.create_task(asyncio.to_thread(builder.build, request, require_work=current))
    try:
        return await asyncio.shield(work)
    except asyncio.CancelledError:
        stopped.set()
        # Cancelling to_thread only detaches it. Keep its task alive until the
        # adapter has killed the process and verified its owned containers gone.
        while not work.done():
            try:
                await asyncio.shield(work)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        try:
            work.result()
        except NativeBuildInterrupted:
            pass
        # Cleanup/ownership failures remain errors, not a successful cancellation.
        raise
