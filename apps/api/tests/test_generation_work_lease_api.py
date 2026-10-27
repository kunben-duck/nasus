"""Real PostgreSQL fencing with canonical fixtures, never paid model calls."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import importlib
import json
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from apps.api.app.application.quality_loop.generation_work_lease import GenerationLeaseBusy, GenerationLeaseLost
from apps.api.app.application.quality_loop.test_design_results import TestDesignResultIntegrityError
from apps.api.app.infrastructure.persistence.generation_job_models import GenerationWorkLeaseRecord as WorkLease
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.test_design_scope_repository import TestDesignScopeRepository
from apps.api.tests.test_generation_execution_api import (
    execution, design_scope, publication, documents, evidence_api, seed, queued, command,
    count, Reservation, Reply, Result, GENERATION_CANCEL_TOOL, invoke, confirm, completed, job,
)


def expire(ident):
    with session_scope() as session:
        session.execute(update(WorkLease).where(WorkLease.invocation_id == ident).values(expires_at=func.clock_timestamp()))


def row_for(ident):
    with session_scope() as session:
        row = session.get(WorkLease, ident)
        return {key: getattr(row, key) for key in ("owner_id", "epoch", "acquired_at", "renewed_at", "expires_at", "request_digest")}


def test_postgres_claim_is_exclusive_and_stale_worker_cannot_renew_release_or_finish(execution):
    v = execution
    ident, repository = seed(v), v["jobs"].repository
    def claim(owner):
        try:
            return repository.claim_lease(v["project_id"], ident, owner)
        except GenerationLeaseBusy:
            return None
    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(claim, [uuid4().hex, uuid4().hex]))
    first = next(value for value in outcomes if value is not None)
    assert sum(value is not None for value in outcomes) == 1 and first.epoch == 1
    original = row_for(ident)
    repository.renew_lease(first)
    assert row_for(ident)["renewed_at"] > original["renewed_at"]
    with pytest.raises(GenerationLeaseBusy):
        asyncio.run(v["jobs"].fail(ident))
    with pytest.raises(GenerationLeaseLost):
        repository.require_lease(replace(first, owner_id="foreign-worker"))
    with pytest.raises(GenerationLeaseLost):
        repository.renew_lease(replace(first, owner_id="foreign-worker"))
    expire(ident)
    with pytest.raises(GenerationLeaseLost):
        repository.renew_lease(first)
    second = repository.claim_lease(v["project_id"], ident, uuid4().hex)
    assert second.epoch == 2
    current = row_for(ident)
    repository.release_lease(first)
    assert row_for(ident) == current
    with pytest.raises(GenerationLeaseLost):
        repository.finish(v["project_id"], ident, "failed", "stale worker", lease=first)
    repository.require_lease(second)
    assert command(v, ident).json()["status"] == "running"
    repository.release_lease(second)
    assert asyncio.run(v["jobs"].fail(ident)) == "failed"
    assert not v["native_calls"]
    assert count(v, Reservation) == count(v, Reply) == count(v, Result) == 0


def test_two_generation_activities_cannot_fail_or_duplicate_a_live_native_call(execution, monkeypatch):
    v = execution
    ident = queued(v)
    original = v["executor"].provider.generate
    async def verify():
        entered, release = asyncio.Event(), asyncio.Event()
        async def waiting(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)
        monkeypatch.setattr(v["executor"].provider, "generate", waiting)
        first = asyncio.create_task(v["jobs"].run(ident))
        try:
            await asyncio.wait_for(entered.wait(), 60)
            assert count(v, Reservation) == 1 and count(v, Reply) == 0
            with pytest.raises(GenerationLeaseBusy):
                await v["jobs"].run(ident)
            with pytest.raises(GenerationLeaseBusy):
                await v["jobs"].fail(ident)
            assert command(v, ident).json()["status"] == "running"
            release.set()
            assert await asyncio.wait_for(first, 60) == "completed"
        finally:
            release.set()
            if not first.done():
                first.cancel()
            await asyncio.gather(first, return_exceptions=True)
    asyncio.run(verify())
    assert len(v["native_calls"]) == 1
    assert count(v, Reservation) == count(v, Reply) == count(v, Result) == 1
    with session_scope() as session:
        now = session.scalar(select(func.clock_timestamp()))
    assert row_for(ident)["expires_at"] <= now
    state = json.dumps(job(v, ident))
    assert "owner_id" not in state and "request_digest" not in state


def test_expired_worker_keeps_unknown_reservation_and_cannot_write_late_reply(execution, monkeypatch):
    v = execution
    ident = queued(v)
    original, successor = v["executor"].provider.generate, []
    async def replaced(*args, **kwargs):
        reply = await original(*args, **kwargs)
        expire(ident)
        successor.append(v["jobs"].repository.claim_lease(v["project_id"], ident, uuid4().hex))
        return reply
    monkeypatch.setattr(v["executor"].provider, "generate", replaced)
    with pytest.raises(GenerationLeaseLost):
        asyncio.run(v["jobs"].run(ident))
    v["jobs"].repository.require_lease(successor[0])
    assert command(v, ident).json()["status"] == "running"
    assert count(v, Reservation) == 1 and count(v, Reply) == count(v, Result) == 0
    v["jobs"].repository.release_lease(successor[0])
    assert asyncio.run(v["jobs"].run(ident)) == "failed"
    assert len(v["native_calls"]) == 1 and row_for(ident)["epoch"] == 3


def test_result_transaction_fences_replaced_worker_and_new_owner_replays_one_archived_reply(execution, monkeypatch):
    v = execution
    ident = queued(v)
    original, successor = v["executor"].results.artifacts.put, []
    def replace_after_private_result_write(*args):
        value = original(*args)
        expire(ident)
        successor.append(v["jobs"].repository.claim_lease(v["project_id"], ident, uuid4().hex))
        return value
    monkeypatch.setattr(v["executor"].results.artifacts, "put", replace_after_private_result_write)
    with pytest.raises(GenerationLeaseLost):
        asyncio.run(v["jobs"].run(ident))
    v["jobs"].repository.require_lease(successor[0])
    assert count(v, Reservation) == count(v, Reply) == 1 and count(v, Result) == 0
    assert command(v, ident).json()["status"] == "running"
    monkeypatch.setattr(v["executor"].results.artifacts, "put", original)
    v["jobs"].repository.release_lease(successor[0])
    assert asyncio.run(v["jobs"].run(ident)) == "completed"
    assert len(v["native_calls"]) == 1 and count(v, Result) == 1
    assert row_for(ident)["epoch"] == 3


def test_canonical_cancel_revokes_lease_but_does_not_refund_or_authorize_new_work(execution):
    v = execution
    ident, repository = queued(v), v["jobs"].repository
    lease = repository.claim_lease(v["project_id"], ident, uuid4().hex)
    pending = invoke(v, GENERATION_CANCEL_TOOL, {"project_id": v["project_id"], "invocation_id": ident}, key=uuid4().hex).json()
    assert pending["status"] == "waiting_confirmation"
    completed(confirm(v, pending))
    assert command(v, ident).json()["status"] == "cancelled"
    with pytest.raises(GenerationLeaseLost):
        repository.require_lease(lease)
    with pytest.raises(GenerationLeaseLost):
        repository.renew_lease(lease)
    with pytest.raises(GenerationLeaseLost):
        repository.claim_lease(v["project_id"], ident, uuid4().hex)
    assert asyncio.run(v["jobs"].run(ident)) == "cancelled" and not v["native_calls"]


@pytest.mark.parametrize("locks", ["project", "command", "both"])
def test_heartbeat_does_not_wait_for_business_validation_locks(execution, locks):
    v = execution
    ident, repository = seed(v), v["jobs"].repository
    lease = repository.claim_lease(v["project_id"], ident, uuid4().hex)
    with ThreadPoolExecutor(max_workers=1) as workers:
        with session_scope() as session:
            if locks in {"project", "both"}:
                TestDesignScopeRepository._lock(session, v["project_id"])
            if locks in {"command", "both"}:
                session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == ident).with_for_update())
            cached = session.get(WorkLease, ident)
            before = cached.renewed_at
            workers.submit(repository.renew_lease, lease).result(timeout=5)
            # A second fence must see the committed heartbeat, not the first
            # lease loaded into this still-open business transaction.
            current = repository._require_lease_state(session, session.get(ToolInvocationRecord, ident), lease)
            assert current is cached and current.renewed_at > before
    repository.require_lease(lease)
    repository.release_lease(lease)
    assert not v["native_calls"]
    assert count(v, Reservation) == count(v, Reply) == count(v, Result) == 0


@pytest.mark.parametrize("mutation", ["project", "canonical_input"])
def test_work_lease_cannot_be_rebound_to_another_project_or_changed_command(execution, mutation):
    v = execution
    ident, repository = seed(v), v["jobs"].repository
    lease = repository.claim_lease(v["project_id"], ident, uuid4().hex)
    if mutation == "project":
        with pytest.raises(GenerationLeaseLost):
            repository.require_lease(replace(lease, project_id="foreign-project"))
    else:
        with session_scope() as session:
            row = session.get(ToolInvocationRecord, ident)
            row.input_payload = {**row.input_payload, "confirmed_at": "2000-01-01T00:00:00+00:00"}
        with pytest.raises(GenerationLeaseLost):
            repository.renew_lease(lease)
        expire(ident)
        with pytest.raises(TestDesignResultIntegrityError):
            repository.claim_lease(v["project_id"], ident, uuid4().hex)
    assert not v["native_calls"]


def test_work_lease_migration_cannot_destroy_execution_receipts(execution):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from apps.api.app.infrastructure.persistence.database import engine
    v = execution
    ident = seed(v)
    v["jobs"].repository.claim_lease(v["project_id"], ident, uuid4().hex)
    migration = importlib.import_module("apps.api.migrations.versions.0062_generation_work_leases")
    with engine.begin() as connection:
        original = migration.op
        try:
            migration.op = Operations(MigrationContext.configure(connection))
            with pytest.raises(RuntimeError, match="cannot downgrade"):
                migration.downgrade()
        finally:
            migration.op = original
