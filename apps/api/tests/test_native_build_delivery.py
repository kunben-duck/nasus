"""Bounded delivery only; no native execution or fake lifecycle authority."""
import asyncio
from types import SimpleNamespace

from apps.api.app.infrastructure.workflow.native_build_runtime import reconcile_native_builds_once


def test_native_delivery_pages_existing_commands_and_does_not_starve_after_unknown_ack():
    identifiers = [f"build-{index:03d}" for index in range(105)]
    started, cancelled, delivered, ended = [], [], [], []
    def page(*, after_id=None):
        return [(ident, "project") for ident in identifiers if after_id is None or ident > after_id][:100]
    async def start(ident):
        started.append(ident)
        if ident == identifiers[0]:
            raise RuntimeError("unknown acknowledgement")
        return ident != identifiers[-1]
    async def cancel(ident):
        cancelled.append(ident)
        if ident == identifiers[1]:
            raise RuntimeError("unknown cancellation acknowledgement")
    repository = SimpleNamespace(pending=page, pending_cancellations=page,
        cancellation_delivered=lambda project, ident: delivered.append(ident),
        finish=lambda project, ident, status: ended.append((ident, status)))
    asyncio.run(reconcile_native_builds_once(SimpleNamespace(start=start, cancel=cancel), repository))
    assert started == cancelled == identifiers
    assert delivered == [ident for ident in identifiers if ident != identifiers[1]]
    assert ended == [(identifiers[-1], "failed")]
