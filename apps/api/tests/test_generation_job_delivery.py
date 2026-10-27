import asyncio
from types import SimpleNamespace

from apps.api.app.infrastructure.workflow.generation_runtime import reconcile_generation_jobs_once


def test_delivery_is_paged_and_an_unavailable_job_does_not_starve_later_intents():
    ids = [f"job-{i:03d}" for i in range(105)]
    started, cancelled, delivered, terminated = [], [], [], []

    def page(*, after_id=None):
        return [(ident, "project") for ident in ids if after_id is None or ident > after_id][:100]

    async def start(ident):
        started.append(ident)
        if ident == ids[0]:
            raise RuntimeError("one workflow unavailable")
        return ident != ids[-1]

    async def cancel(ident):
        cancelled.append(ident)
        if ident == ids[1]:
            raise RuntimeError("one cancellation unavailable")

    repository = SimpleNamespace(pending=page, pending_cancellations=page,
        cancellation_delivered=lambda project, ident: delivered.append(ident),
        finish=lambda project, ident, status, summary: terminated.append((ident, status)))
    asyncio.run(reconcile_generation_jobs_once(SimpleNamespace(start=start, cancel=cancel), repository))
    assert started == cancelled == ids
    assert delivered == [ident for ident in ids if ident != ids[1]]
    assert terminated == [(ids[-1], "failed")]
