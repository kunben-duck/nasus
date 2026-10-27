"""Scheduling specimens: completion/cancellation must join actual worker threads."""
import asyncio
from threading import Event
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.generation_work_lease import run_with_generation_lease
from apps.api.app.application.quality_loop.http_fixture_work import run_with_http_fixture_work
from apps.api.tests.test_http_fixture_work import work


@pytest.mark.parametrize("fixture", [False, True])
@pytest.mark.parametrize("cancel", [False, True])
def test_success_or_cancel_joins_in_flight_renewal_before_returning(fixture, cancel):
    lease = work()
    started, release, finished = Event(), Event(), Event()
    calls = []
    def renew(*args, **kwargs):
        started.set()
        try:
            assert release.wait(2), "test must always release its owned renewal thread"
            calls.append("renewed")
        finally:
            finished.set()
    async def exercise():
        complete = asyncio.Event()
        async def operation(require_work):
            await complete.wait()
            return "original-result"
        if fixture:
            task = asyncio.create_task(run_with_http_fixture_work(SimpleNamespace(require=lambda _value: None,
                renew=renew), lease, operation, require_current=lambda: None, renew_seconds=0.001))
        else:
            task = asyncio.create_task(run_with_generation_lease(SimpleNamespace(require_lease=lambda _value: None,
                renew_lease=renew), lease, operation, renew_seconds=0.001))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            if cancel: task.cancel()
            else: complete.set()
            await asyncio.sleep(0.02)
            assert not task.done(), "lifecycle returned while its renewal can still write"
            release.set()
            if cancel:
                with pytest.raises(asyncio.CancelledError): await task
            else:
                assert await task == "original-result"
            assert finished.is_set() and calls == ["renewed"]
            assert not [value for value in asyncio.all_tasks() if value is not asyncio.current_task()]
        finally:
            release.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())


@pytest.mark.parametrize("repeat", [False, True])
def test_cancelled_initial_lease_check_is_joined_and_cannot_start_the_operation(repeat):
    lease = work()
    started, release, finished = Event(), Event(), Event()
    calls = []
    def require_lease(_value):
        started.set()
        try: assert release.wait(2)
        finally: finished.set()
    async def exercise():
        async def operation(require_work): calls.append("unexpected-operation")
        task = asyncio.create_task(run_with_generation_lease(SimpleNamespace(require_lease=require_lease,
            renew_lease=lambda _value: None), lease, operation, renew_seconds=1))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            task.cancel()
            await asyncio.sleep(0.01)
            if repeat: task.cancel()
            await asyncio.sleep(0.01)
            assert not task.done(), "cancelled lease check still owns a live thread"
            release.set()
            with pytest.raises(asyncio.CancelledError): await task
            assert finished.is_set() and not calls
            assert not [value for value in asyncio.all_tasks() if value is not asyncio.current_task()]
        finally:
            release.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())
