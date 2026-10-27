"""A worker lease fences execution, never grants model egress or refunds calls."""
import asyncio
from dataclasses import dataclass

from .worker_threads import run_worker_thread

GENERATION_LEASE_SECONDS = 90
GENERATION_LEASE_RENEW_SECONDS = 15


class GenerationLeaseBusy(RuntimeError):
    pass


class GenerationLeaseLost(RuntimeError):
    pass


@dataclass(frozen=True)
class GenerationWorkLease:
    project_id: str
    invocation_id: str
    owner_id: str
    epoch: int
    request_digest: str

    def __post_init__(self):
        if (any(type(value) is not str or not value or len(value) > 128
                for value in (self.project_id, self.invocation_id, self.owner_id))
                or type(self.epoch) is not int or self.epoch < 1):
            raise ValueError("invalid generation worker lease")
        if (type(self.request_digest) is not str or len(self.request_digest) != 71
                or not self.request_digest.startswith("sha256:")
                or any(char not in "0123456789abcdef" for char in self.request_digest[7:])):
            raise ValueError("invalid generation lease request digest")


async def run_with_generation_lease(repository, lease, operation, *, renew_seconds=GENERATION_LEASE_RENEW_SECONDS):
    """Cancel an in-flight adapter on lost ownership; DB commit guards still fence threads."""
    async def renew():
        while True:
            await asyncio.sleep(renew_seconds)
            await run_worker_thread(lambda: repository.renew_lease(lease))

    async def execute():
        await run_worker_thread(lambda: repository.require_lease(lease))
        return await operation(lambda: repository.require_lease(lease))

    work, heartbeat = asyncio.create_task(execute()), asyncio.create_task(renew())
    try:
        done, _ = await asyncio.wait({work, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
        if work not in done:
            await heartbeat
            raise GenerationLeaseLost("generation lease renewal stopped")
        return await work
    finally:
        # Each synchronous lease check/renewal joins before its task finishes;
        # side-effecting operations still need their own transactional fences.
        heartbeat.cancel()
        work.cancel()
        await asyncio.gather(work, heartbeat, return_exceptions=True)
