import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.domain.system_image.structure_work import StructureWorkBusy, StructureWorkLost
from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord, ToolInvocationRecord, UserIdentityRecord
from apps.api.app.infrastructure.persistence.structure_build_models import StructureBuildArtifactRecord
from apps.api.app.infrastructure.persistence.structure_job_models import StructureJobRecord, StructureWorkLeaseRecord
from apps.api.app.infrastructure.persistence.structure_job_repository import StructureJobRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.workflow.structure_runtime import reconcile_structure_jobs_once
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_structure_build_api import request, submit, confirm
from apps.api.tests.test_code_index_lifecycle_api import install_native, generation


@pytest.fixture
def queued(evidence_api, monkeypatch):
    v = evidence_api
    jobs = app.state.container.structure_jobs
    calls = []

    async def start(ident):
        calls.append(ident)
        return True

    monkeypatch.setattr(type(jobs.workflow), "enabled", property(lambda _: True))
    monkeypatch.setattr(jobs.workflow, "start", start)
    v.update(jobs=jobs, dispatched=calls)
    return v


def enqueue(v):
    payload = request(v)
    ident = submit(v, payload)
    response = confirm(v, ident)
    assert response["status"] == "running" and response["result"] is None
    assert v["dispatched"] == [ident]
    with session_scope() as session:
        job = session.get(StructureJobRecord, ident)
        assert job.request_payload == payload and job.actor_id == v["owner"]["id"]
        assert session.get(StructureBuildArtifactRecord, ident) is None
    return ident, payload


def test_confirmation_returns_queued_then_native_worker_commits_once(queued, monkeypatch, tmp_path):
    v = queued
    _, log = install_native(v, monkeypatch, tmp_path)
    ident, payload = enqueue(v)
    before = log.read_text() if log.exists() else ""
    # HTTP confirmation never starts the native provider itself.
    assert "index_repository" not in before
    assert asyncio.run(v["jobs"].run(ident)) == "completed"
    pin = generation(ident)
    committed = confirm(v, ident)
    assert committed["status"] == "completed" and "image_revision:" in str(committed["result"]["object_refs"])
    after = log.read_text()
    assert asyncio.run(v["jobs"].run(ident)) == "completed" and log.read_text() == after
    assert generation(ident) == pin
    with session_scope() as session:
        assert session.get(StructureWorkLeaseRecord, ident).epoch == 1
        audit = session.scalars(select(AuditEventRecord).where(
            AuditEventRecord.tool_invocation_id == ident, AuditEventRecord.action == "tool.invocation.completed")).one()
        assert (audit.entity_type, audit.entity_id, audit.status) == ("tool_invocation", ident, "completed")
        assert audit.event_metadata == {"project_id": v["project_id"], "actor_id": v["owner"]["id"]}
        assert len(session.scalars(select(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_type == "system_image.build.structure.completed",
            SSEEventOutboxRecord.entity_id == payload["plan_id"])).all()) == 1
    assert v["dispatched"] == [ident]


def test_dispatch_acknowledgement_failure_preserves_intent_for_reconciliation(queued, monkeypatch):
    v = queued
    async def unavailable(ident):
        v["dispatched"].append(ident)
        raise OSError("private endpoint detail")
    monkeypatch.setattr(v["jobs"].workflow, "start", unavailable)
    ident, _ = enqueue(v)
    assert v["jobs"].repository.command(ident)[1] == "running"
    delivered = []
    async def restarted(ident):
        delivered.append(ident)
        return True
    monkeypatch.setattr(v["jobs"].workflow, "start", restarted)
    asyncio.run(reconcile_structure_jobs_once(v["jobs"].workflow, StructureJobRepository()))
    assert ident in delivered
    assert asyncio.run(v["jobs"].run(ident)) == "completed"


def test_expired_owner_is_fenced_and_original_pins_survive(queued):
    v = queued
    ident, _ = enqueue(v)
    repo = v["jobs"].repository
    first = repo.claim(ident, "first")
    with pytest.raises(StructureWorkBusy):
        repo.claim(ident, "second")
    with session_scope() as session:
        session.get(StructureWorkLeaseRecord, ident).expires_at = session.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
    second = repo.claim(ident, "second")
    assert second.epoch == 2 and second.command_hash == first.command_hash
    for operation in (lambda: repo.renew(first), lambda: repo.finish(ident, "failed", lease=first)):
        with pytest.raises(StructureWorkLost):
            operation()
    repo.release(first)
    with session_scope() as session:
        assert session.get(StructureWorkLeaseRecord, ident).owner_id == "second"
    repo.release(second)
    assert asyncio.run(v["jobs"].run(ident)) == "completed"
    with session_scope() as session:
        assert session.get(StructureWorkLeaseRecord, ident).epoch == 3


@pytest.mark.parametrize("kind", ["plan_digest", "confirmed_at", "target_baseline_id"])
def test_dispatch_refuses_mutated_canonical_input(queued, kind):
    v = queued
    ident, _ = enqueue(v)
    with session_scope() as session:
        command = session.get(ToolInvocationRecord, ident)
        command.input_payload = {**command.input_payload, kind: "changed"}
    with pytest.raises(BuildPlanIntegrityError):
        asyncio.run(v["jobs"].run(ident))
    with session_scope() as session:
        assert session.get(StructureBuildArtifactRecord, ident) is None


def test_disabled_confirmer_never_executes_or_commits(queued, monkeypatch):
    v = queued
    ident, _ = enqueue(v)
    def forbidden(*args, **kwargs):
        raise AssertionError("disabled actor must not reach structural work")
    monkeypatch.setattr(v["jobs"].application, "execute", forbidden)
    with session_scope() as session:
        session.get(UserIdentityRecord, v["owner"]["id"]).status = "disabled"
    try:
        assert asyncio.run(v["jobs"].run(ident)) == "failed"
        with session_scope() as session:
            assert session.get(StructureBuildArtifactRecord, ident) is None
    finally:
        with session_scope() as session:
            session.get(UserIdentityRecord, v["owner"]["id"]).status = "active"


def test_job_is_append_only_and_stale_worker_cannot_commit_candidate(queued, monkeypatch):
    v = queued
    ident, _ = enqueue(v)
    for statement in (update(StructureJobRecord).values(command_hash="changed"), delete(StructureJobRecord)):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement.where(StructureJobRecord.invocation_id == ident))
    archive = v["jobs"].application.preparation.candidates.artifacts
    original = archive.put
    replacement = []
    def steal(*args, **kwargs):
        value = original(*args, **kwargs)
        with session_scope() as session:
            session.get(StructureWorkLeaseRecord, ident).expires_at = session.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
        replacement.append(v["jobs"].repository.claim(ident, "successor"))
        return value
    monkeypatch.setattr(archive, "put", steal)
    with pytest.raises(StructureWorkLost):
        asyncio.run(v["jobs"].run(ident))
    with session_scope() as session:
        assert session.get(StructureBuildArtifactRecord, ident) is None
        assert session.get(ToolInvocationRecord, ident).status == "running"
        assert session.get(StructureWorkLeaseRecord, ident).owner_id == "successor"
    v["jobs"].repository.release(replacement[0])
    monkeypatch.setattr(archive, "put", original)
    assert asyncio.run(v["jobs"].run(ident)) == "completed"


def test_interrupted_activity_stops_thread_before_releasing_owner(queued, monkeypatch):
    v = queued
    ident, _ = enqueue(v)
    entered, exited = Event(), Event()
    original = v["jobs"].application.execute
    def slow(*args, require_work, **kwargs):
        entered.set()
        try:
            while True:
                require_work()
                exited.wait(0.01)
        finally:
            exited.set()
    monkeypatch.setattr(v["jobs"].application, "execute", slow)
    async def interrupt():
        task = asyncio.create_task(v["jobs"].run(ident))
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert exited.is_set()
    asyncio.run(interrupt())
    assert v["jobs"].repository.command(ident)[1] == "running"
    monkeypatch.setattr(v["jobs"].application, "execute", original)
    assert asyncio.run(v["jobs"].run(ident)) == "completed"


def test_concurrent_workers_claim_only_one_live_epoch(queued):
    ident, _ = enqueue(queued)
    def claim(owner):
        try:
            return StructureJobRepository().claim(ident, owner)
        except StructureWorkBusy:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim, owner) for owner in ("first", "second")]
        leases = [future.result(timeout=10) for future in futures]
    live = [lease for lease in leases if lease is not None]
    assert len(live) == 1 and live[0].epoch == 1
    queued["jobs"].repository.release(live[0])


def test_candidate_committed_before_ack_loss_is_not_rebuilt(queued, monkeypatch, tmp_path):
    v = queued
    _, log = install_native(v, monkeypatch, tmp_path)
    ident, _ = enqueue(v)
    finish = v["jobs"].repository.finish
    lost = []
    def interrupted(*args, **kwargs):
        if not lost:
            lost.append(True)
            raise OSError("fixture completion acknowledgement lost")
        return finish(*args, **kwargs)
    monkeypatch.setattr(v["jobs"].repository, "finish", interrupted)
    with pytest.raises(OSError):
        asyncio.run(v["jobs"].run(ident))
    before = log.read_text()
    with session_scope() as session:
        candidate = session.get(StructureBuildArtifactRecord, ident).image_revision_id
        assert session.get(ToolInvocationRecord, ident).status == "running"
    assert asyncio.run(v["jobs"].run(ident)) == "completed"
    assert log.read_text() == before
    with session_scope() as session:
        assert session.get(StructureBuildArtifactRecord, ident).image_revision_id == candidate
        assert session.get(StructureWorkLeaseRecord, ident).epoch == 2


def test_queue_delay_does_not_reset_original_confirmation_budget(queued, monkeypatch, tmp_path):
    from apps.api.app.application.system_image import structure_builds
    v = queued
    _, log = install_native(v, monkeypatch, tmp_path)
    ident, _ = enqueue(v)
    with session_scope() as session:
        original = session.get(ToolInvocationRecord, ident).input_payload.copy()
    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return super().now(tz) + timedelta(days=2)
    monkeypatch.setattr(structure_builds, "datetime", Later)
    assert asyncio.run(v["jobs"].run(ident)) == "failed"
    assert not log.exists() or "index_repository" not in log.read_text()
    with session_scope() as session:
        assert session.get(StructureBuildArtifactRecord, ident) is None
        assert session.get(ToolInvocationRecord, ident).input_payload == original
