"""Real application scope ownership; journal/target remain explicit specimens."""
import asyncio
from copy import deepcopy
from threading import Event, Thread

import pytest

from apps.api.app.application.system_image.image_revision_queries import ImageRevisionQueryApplicationService
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureOutcomeUnknown
from apps.api.tests.test_http_fixtures import manifest, scope, service


@pytest.fixture
def phase_reader(monkeypatch):
    application, runner, journal = service()
    images = ImageRevisionQueryApplicationService(None, None, None)
    observations = []

    def observe(label):
        owned = images._verified_read_scope.get()
        proof = images._current_verified_reads()
        assert owned is not None and owned.is_current and proof is not None
        proof.setdefault("complete-original-proof-specimen", object())
        observations.append((label, owned, proof["complete-original-proof-specimen"]))

    monkeypatch.setattr(journal, "verified_read_session", lambda: images.verified_read_session(reuse=True), raising=False)
    for label in ("inspect", "claim", "complete"):
        original = getattr(journal, label)

        def checked(*args, _label=label, _original=original, **kwargs):
            observe(_label)
            return _original(*args, **kwargs)

        monkeypatch.setattr(journal, label, checked)
    original_payload = runner.payload

    def payload(command):
        observe("native-response")
        return original_payload(command)

    runner.payload = payload
    return application, runner, journal, images, observations, observe


def test_each_original_phase_shares_proof_without_skipping_guards_or_replaying_effects(phase_reader):
    application, runner, journal, images, observations, observe = phase_reader
    value, selected = manifest(), scope()
    original = deepcopy(value)
    prepared = application.prepare(selected, value, require_work=lambda: observe("current-authority"))
    first = observations[0][1]
    first_count = len(observations)
    assert first_count > 8 and all(owner is first for _, owner, _ in observations)
    assert sum(label == "current-authority" for label, _, _ in observations) == 9
    assert len({id(proof) for _, _, proof in observations}) == 1
    assert not first.is_open and images._current_verified_reads() is None
    assert len(runner.commands) == 1 and value == original

    cleaned = application.cleanup(selected, value, require_work=lambda: observe("current-authority"))
    cleanup = observations[first_count:]
    assert cleaned.cleanup_verified and len(runner.commands) == 2
    assert len({id(owner) for _, owner, _ in cleanup}) == 2
    assert all(owner is not first and not owner.is_open for _, owner, _ in cleanup)
    before = len(observations)
    assert application.prepare(selected, value, require_work=lambda: observe("current-authority")) == prepared
    replay = observations[before:]
    assert len({id(owner) for _, owner, _ in replay}) == 1
    assert all(owner is not first and not owner.is_open for _, owner, _ in replay)
    assert not any(label in {"claim", "complete", "native-response"} for label, _, _ in replay)
    assert len(runner.commands) == 2 and images._current_verified_reads() is None


@pytest.mark.parametrize("fail_at", [1, 4, 7, 8])
def test_current_authority_is_never_cached_and_failure_closes_owned_proof(phase_reader, fail_at):
    application, runner, journal, images, observations, observe = phase_reader
    count = 0

    def current():
        nonlocal count
        observe("current-authority")
        count += 1
        if count >= fail_at:
            raise PermissionError("explicit source or execution authority revoked")

    with pytest.raises(PermissionError):
        application.prepare(scope(), manifest(), require_work=current)
    # The runner exception path performs another live guard before classifying it.
    assert count == fail_at + (1 if fail_at == 4 else 0)
    assert images._current_verified_reads() is None
    assert observations and all(not owner.is_open for _, owner, _ in observations)
    assert len(runner.commands) <= 1
    if journal.records:
        # An original reserved/unknown effect stays reserved; no new attempt.
        before = deepcopy(journal.records)
        with pytest.raises(HttpFixtureOutcomeUnknown):
            application.prepare(scope(), manifest(), require_work=lambda: observe("fresh-authority"))
        assert journal.records == before


def test_transport_failure_closes_scope_and_unknown_effect_is_never_resent(phase_reader):
    application, runner, journal, images, observations, observe = phase_reader
    runner.failure = TimeoutError("explicit unknown native response")
    with pytest.raises(HttpFixtureOutcomeUnknown):
        application.prepare(scope(), manifest(), require_work=lambda: observe("current-authority"))
    first = observations[0][1]
    assert not first.is_open and images._current_verified_reads() is None
    before = deepcopy(journal.records)
    with pytest.raises(HttpFixtureOutcomeUnknown):
        application.prepare(scope(), manifest(), require_work=lambda: observe("current-authority"))
    assert len(runner.commands) == 1 and journal.records == before


def test_heartbeat_thread_cannot_inherit_dispatch_phase_proof(phase_reader):
    application, runner, journal, images, observations, observe = phase_reader
    from contextvars import copy_context
    original = runner.payload
    heartbeat = []

    def payload(command):
        parent = images._current_verified_reads()
        inherited = copy_context()

        def renew_specimen():
            assert images._current_verified_reads() is None
            with images.verified_read_session(reuse=True):
                heartbeat.append(images._verified_read_scope.get())
                assert images._current_verified_reads() is not parent
            assert images._current_verified_reads() is None

        thread = Thread(target=lambda: inherited.run(renew_specimen))
        thread.start()
        thread.join(5)
        assert not thread.is_alive() and images._current_verified_reads() is parent
        return original(command)

    runner.payload = payload
    application.prepare(scope(), manifest(), require_work=lambda: observe("current-authority"))
    assert len(heartbeat) == 1 and not heartbeat[0].is_open
    assert all(owner is not heartbeat[0] for _, owner, _ in observations)


def test_async_cancellation_joins_and_closes_owned_phase_before_returning(phase_reader):
    application, runner, journal, images, observations, observe = phase_reader
    from apps.api.app.application.quality_loop.worker_threads import run_worker_thread
    started, stop = Event(), Event()
    original = runner.payload

    def payload(command):
        started.set()
        assert stop.wait(5)
        return original(command)

    runner.payload = payload

    def current():
        observe("current-authority")
        if stop.is_set():
            raise PermissionError("explicit cancelled phase cannot commit")

    async def cancel():
        work = asyncio.create_task(run_worker_thread(
            lambda: application.prepare(scope(), manifest(), require_work=current), on_cancel=stop.set))
        assert await asyncio.to_thread(started.wait, 5)
        work.cancel()
        with pytest.raises(asyncio.CancelledError):
            await work

    asyncio.run(cancel())
    assert len(runner.commands) == 1 and images._current_verified_reads() is None
    assert all(not owner.is_open for _, owner, _ in observations)
    assert all(record.execution is None for record in journal.records.values())
