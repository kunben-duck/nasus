import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.generation_work_lease import (
    GenerationLeaseLost, GenerationWorkLease, run_with_generation_lease,
)
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.tests.test_generation_executor import executor
from apps.api.app.application.quality_loop.test_design_results import GenerationResultRequest


def lease():
    return GenerationWorkLease("project", "invocation", "worker", 1, acceptance_digest("request"))


@pytest.mark.parametrize("changes", [{"epoch": 0}, {"epoch": True}, {"owner_id": ""}, {"project_id": None},
    {"invocation_id": "x" * 129}, {"request_digest": "not-a-digest"}])
def test_invalid_worker_lease_cannot_be_created(changes):
    with pytest.raises(ValueError):
        replace(lease(), **changes)


def test_lease_guard_is_checked_before_work_and_no_task_survives_success():
    async def verify():
        checked, renewed = [], []
        repository = SimpleNamespace(require_lease=lambda value: checked.append(value), renew_lease=lambda value: renewed.append(value))
        async def work(require_work):
            require_work()
            return "completed"
        assert await run_with_generation_lease(repository, lease(), work, renew_seconds=1) == "completed"
        assert checked == [lease(), lease()] and not renewed
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
    asyncio.run(verify())


def test_initial_lost_lease_prevents_the_operation():
    async def verify():
        calls = []
        def lost(value):
            raise GenerationLeaseLost("expired")
        async def work(require_work):
            calls.append(1)
        with pytest.raises(GenerationLeaseLost):
            await run_with_generation_lease(SimpleNamespace(require_lease=lost, renew_lease=lost), lease(), work)
        assert not calls
    asyncio.run(verify())


@pytest.mark.parametrize("error", [GenerationLeaseLost("replaced"), RuntimeError("database unavailable")])
def test_renewal_failure_cancels_waiting_model_and_propagates_without_business_failure(error):
    async def verify():
        waiting, cancelled, renewed = asyncio.Event(), [], []
        def renew(value):
            renewed.append(value)
            raise error
        async def work(require_work):
            waiting.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(1)
                raise
        task = asyncio.create_task(run_with_generation_lease(SimpleNamespace(require_lease=lambda value: None,
            renew_lease=renew), lease(), work, renew_seconds=0.01))
        await waiting.wait()
        with pytest.raises(type(error)):
            await task
        assert renewed == [lease()] and cancelled == [1]
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
    asyncio.run(verify())


def test_outer_cancellation_stops_both_work_and_renewal():
    async def verify():
        waiting, cancelled = asyncio.Event(), []
        async def work(require_work):
            waiting.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(1)
                raise
        task = asyncio.create_task(run_with_generation_lease(SimpleNamespace(require_lease=lambda value: None,
            renew_lease=lambda value: None), lease(), work, renew_seconds=0.01))
        await waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled == [1]
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
    asyncio.run(verify())


@pytest.mark.parametrize("stage", ["before_reservation", "after_native_reply", "after_private_write"])
def test_executor_fences_model_and_receipt_writes_without_releasing_unknown_calls(stage):
    application, selection, deps, _ = executor()
    request = GenerationResultRequest.model_validate(application.preview(selection)["request"])
    lost = [stage == "before_reservation"]
    def require_work():
        if lost[0]:
            raise GenerationLeaseLost("replaced worker")
    original = deps["provider"].generate
    if stage == "after_native_reply":
        async def reply(*args, **kwargs):
            value = await original(*args, **kwargs)
            lost[0] = True
            return value
        deps["provider"].generate = reply
    elif stage == "after_private_write":
        put = deps["artifacts"].put
        def private_write(*args):
            value = put(*args)
            lost[0] = True
            return value
        deps["artifacts"].put = private_write
    with pytest.raises(GenerationLeaseLost):
        asyncio.run(application.execute(request, invocation_id="invocation", require_work=require_work))
    assert deps["results"].calls == 0
    if stage == "before_reservation":
        assert not deps["repository"].stored and deps["provider"].calls == 0
    else:
        assert deps["provider"].calls == 1 and deps["repository"].stored["reply"] is None
        assert deps["repository"].calls[0].outcome == "error"
