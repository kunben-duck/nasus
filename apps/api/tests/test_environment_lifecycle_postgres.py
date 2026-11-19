"""Run via scripts/test-api-postgres.py; never creates tables in a developer DB.

All target proofs are explicitly synthetic. These tests exercise the metadata
protocol, not an actual database snapshot, business execution, or reset.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import importlib.util
import os
from pathlib import Path
import re
from threading import Barrier
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from apps.api.app.application.quality_loop.environment_lifecycle import EnvironmentLifecycleService
from apps.api.app.domain.quality_loop.execution_environment_lifecycle import (
    EnvironmentFenceRejected, EnvironmentLeaseUnavailable, EnvironmentLifecycleInvalid,
    EnvironmentOperationFailed, ExecutionStoppedProof, RegisteredExecutionEnvironment,
)
# Direct import is intentional: migration discovery must not depend on parent wiring.
from apps.api.app.infrastructure.persistence.execution_environment_models import (
    ExecutionEnvironmentLeaseRecord as Lease, ExecutionEnvironmentRecord as Environment,
    ExecutionEnvironmentSnapshotRecord as Snapshot,
    ExecutionEnvironmentSnapshotRestoreRecord as Restore,
)
from apps.api.app.infrastructure.persistence.execution_environment_repository import PostgresExecutionEnvironmentRepository
from apps.api.app.infrastructure.runner.execution_vault import ExecutionEnvelopeCipher
from apps.api.app.infrastructure.storage.execution_snapshots import ExecutionSnapshotStorage
from apps.api.tests.test_environment_lifecycle import SpecimenAccess, SpecimenObjects, SpecimenTarget


@pytest.fixture(scope="module")
def pg():
    connection = os.environ.get("NASUS_TEST_DATABASE_URL")
    if not connection:
        pytest.skip("requires scripts/test-api-postgres.py disposable database harness")
    url = make_url(connection)
    if (url.get_backend_name() != "postgresql" or url.host not in {"localhost", "127.0.0.1", "::1"}
            or not re.fullmatch(r"nasus_test_[0-9a-f]{32}", url.database or "")
            or connection != os.environ.get("NASUS_DATABASE_URL")):
        pytest.fail("refusing lifecycle test writes outside the isolated PostgreSQL harness")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT current_database()")) == url.database
            assert set(inspect(conn).get_table_names()) >= {
                Environment.__tablename__, Lease.__tablename__, Snapshot.__tablename__, Restore.__tablename__}
        yield engine, sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()


@pytest.fixture
def registered(pg):
    _, sessions = pg
    repo = PostgresExecutionEnvironmentRepository(sessions)
    registration = RegisteredExecutionEnvironment("env-" + uuid4().hex, "project",
        "target-" + uuid4().hex, "sha256:" + "a" * 64, 1024)
    repo.register(registration)
    return repo, registration


def acquire(repo, registration, **overrides):
    args = dict(environment_id=registration.environment_id, project_id=registration.project_id,
                version_id="version", batch_id="batch", owner_id="owner", ttl_seconds=60)
    args.update(overrides)
    return repo.acquire(**args)


def state(pg, lease):
    with pg[1]() as session:
        environment, row = session.get(Environment, lease.environment_id), session.get(Lease, lease.lease_id)
        return environment.state, row.phase, row.quarantine_reason, row.reset_verified


def specimen_service(repo, registration, monkeypatch):
    target, objects = SpecimenTarget(), SpecimenObjects()
    monkeypatch.setattr(target, "resolve", lambda key: target if key == registration.target_key else None)
    return EnvironmentLifecycleService(repository=repo, access=SpecimenAccess(), targets=target,
        snapshots=ExecutionSnapshotStorage(objects, ExecutionEnvelopeCipher(b"x" * 32, "test-key"),
                                          anonymous_client_factory=lambda: objects)), target, objects


def test_registered_environment_has_one_durable_exclusive_owner_across_processes(pg, registered):
    repo, registration = registered
    barrier = Barrier(6)

    def contender(index):
        # Independent repositories/sessions model distinct worker processes.
        contender_repo = PostgresExecutionEnvironmentRepository(pg[1])
        barrier.wait(timeout=10)
        try:
            return acquire(contender_repo, registration, owner_id="owner-" + str(index))
        except EnvironmentLeaseUnavailable:
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(contender, range(6)))
    winners = [lease for lease in results if lease is not None]
    assert len(winners) == 1
    lease = winners[0]
    PostgresExecutionEnvironmentRepository(pg[1]).require_live(lease, phases=("leased",))
    with pg[1]() as session:
        rows = session.scalars(select(Lease).where(Lease.environment_id == registration.environment_id)).all()
        assert len(rows) == 1 and rows[0].owner_id == lease.owner_id
        now = session.scalar(text("SELECT clock_timestamp()"))
        assert lease.created_at <= now < lease.expires_at
        assert (lease.expires_at - lease.created_at).total_seconds() == 60


def test_generation_fences_old_owner_and_old_quarantine_cannot_touch_new_owner(pg, registered):
    repo, registration = registered
    first = acquire(repo, registration)
    repo.release(first)
    second = acquire(repo, registration)
    assert second.generation == first.generation + 1
    with pytest.raises(EnvironmentFenceRejected):
        repo.transition(first, expected=("leased",), phase="capturing_before")
    repo.quarantine(first, reason="capture_failed")
    repo.require_live(second, phases=("leased",))
    assert state(pg, second) == ("leased", "leased", None, False)


@pytest.mark.parametrize("field,value", [("owner_id", "other"), ("batch_id", "other"),
    ("version_id", "other"), ("project_id", "other"), ("target_key", "other"),
    ("inventory_hash", "sha256:" + "b" * 64), ("generation", 2), ("max_snapshot_bytes", 100)])
def test_caller_cannot_rebind_durable_lease(registered, field, value):
    repo, registration = registered
    lease = acquire(repo, registration)
    with pytest.raises(EnvironmentFenceRejected):
        repo.require_live(replace(lease, **{field: value}), phases=("leased",))
    repo.require_live(lease, phases=("leased",))


@pytest.mark.parametrize("ttl", [0, -1, 901, True, 1.5])
def test_bounded_lease_rejects_unbounded_duration(registered, ttl):
    repo, registration = registered
    with pytest.raises(EnvironmentLifecycleInvalid):
        acquire(repo, registration, ttl_seconds=ttl)


@pytest.mark.parametrize("entry", ["require_live", "acquire", "reap_expired"])
def test_expired_lease_is_committed_to_quarantine_without_automatic_takeover(pg, registered, entry):
    repo, registration = registered
    lease = acquire(repo, registration, ttl_seconds=1)
    repo.transition(lease, expected=("leased",), phase="capturing_before")
    with pg[0].connect() as conn:
        conn.execute(text("SELECT pg_sleep(1.05)"))
    if entry == "require_live":
        with pytest.raises(EnvironmentFenceRejected):
            repo.require_live(lease, phases=("capturing_before",))
    elif entry == "acquire":
        with pytest.raises(EnvironmentLeaseUnavailable):
            acquire(repo, registration)
    else:
        assert repo.reap_expired(lease.environment_id)
        assert not repo.reap_expired(lease.environment_id)
    assert state(pg, lease) == ("quarantined", "quarantined", "expired", False)
    with pytest.raises(EnvironmentLeaseUnavailable):
        acquire(repo, registration)


def test_interrupted_before_claim_survives_new_repository_and_cannot_be_replayed(pg, registered):
    repo, registration = registered
    lease = acquire(repo, registration, ttl_seconds=1)
    repo.transition(lease, expected=("leased",), phase="capturing_before")
    restarted = PostgresExecutionEnvironmentRepository(pg[1])
    with pytest.raises(EnvironmentFenceRejected):
        restarted.transition(lease, expected=("leased",), phase="capturing_before")
    with pytest.raises(EnvironmentFenceRejected):
        restarted.transition(lease, expected=("before_ready",), phase="running")
    with pg[0].connect() as conn:
        conn.execute(text("SELECT pg_sleep(1.05)"))
    assert restarted.reap_expired(lease.environment_id)
    assert state(pg, lease)[0] == "quarantined"


def test_lease_expiring_while_waiting_for_row_lock_cannot_be_used(pg, registered):
    repo, registration = registered
    lease = acquire(repo, registration, ttl_seconds=1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pg[0].begin() as conn:
            conn.execute(text("SELECT environment_id FROM quality_execution_environments "
                              "WHERE environment_id = :id FOR UPDATE"), {"id": lease.environment_id})
            waiter = pool.submit(repo.require_live, lease, phases=("leased",))
            conn.execute(text("SELECT pg_sleep(1.05)"))
        with pytest.raises(EnvironmentFenceRejected):
            waiter.result(timeout=5)
    assert state(pg, lease) == ("quarantined", "quarantined", "expired", False)


def test_capture_claim_is_exclusive_and_not_replayed_after_restart(pg, registered):
    repo, registration = registered
    lease = acquire(repo, registration)
    barrier = Barrier(2)

    def claim():
        contender = PostgresExecutionEnvironmentRepository(pg[1])
        barrier.wait(timeout=5)
        try:
            contender.transition(lease, expected=("leased",), phase="capturing_before")
            return True
        except EnvironmentFenceRejected:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(claim), pool.submit(claim)
        assert sorted([first.result(timeout=5), second.result(timeout=5)]) == [False, True]
    restarted = PostgresExecutionEnvironmentRepository(pg[1])
    with pytest.raises(EnvironmentFenceRejected):
        restarted.transition(lease, expected=("leased",), phase="capturing_before")


@pytest.mark.parametrize("phase", ["leased", "before_ready", "running", "stopping", "stopped", "capturing_after"])
def test_reset_cannot_skip_snapshot_or_stop_guards(registered, phase, monkeypatch):
    repo, registration = registered
    lease = acquire(repo, registration)
    service, _, _ = specimen_service(repo, registration, monkeypatch)
    if phase != "leased":
        service.capture(lease, phase="before")
    if phase not in {"leased", "before_ready"}:
        service.mark_running(lease)
    if phase == "stopping":
        repo.transition(lease, expected=("running",), phase="stopping")
    elif phase in {"stopped", "capturing_after"}:
        service.stop(lease)
        if phase == "capturing_after":
            repo.transition(lease, expected=("stopped",), phase="capturing_after")
    with pytest.raises(EnvironmentFenceRejected):
        repo.transition(lease, expected=("after_ready",), phase="resetting")


@pytest.mark.parametrize("fault", ["capture", "unverified", "reset", "readback"])
def test_service_failures_quarantine_durably_without_reuse(pg, registered, monkeypatch, fault):
    repo, registration = registered
    service, target, objects = specimen_service(repo, registration, monkeypatch)
    lease = acquire(repo, registration)
    if fault == "capture":
        target.failure = "capture"
    if fault == "unverified":
        target.snapshot_valid = False
    if fault in {"capture", "unverified"}:
        with pytest.raises(EnvironmentOperationFailed):
            service.capture(lease, phase="before")
    else:
        service.capture(lease, phase="before")
        service.mark_running(lease)
        service.stop(lease)
        archived = service.capture(lease, phase="after")
        assert archived.restore_verified and not state(pg, lease)[3]
        if fault == "reset":
            target.failure = "reset"
        else:
            objects.corrupt = True
        with pytest.raises(EnvironmentOperationFailed):
            service.reset(lease)
    assert state(pg, lease)[0:2] == ("quarantined", "quarantined")
    assert state(pg, lease)[3] is False
    with pytest.raises(EnvironmentLeaseUnavailable):
        acquire(repo, registration)


def test_complete_synthetic_protocol_retains_snapshot_and_real_generation(pg, registered, monkeypatch):
    repo, registration = registered
    service, target, _ = specimen_service(repo, registration, monkeypatch)
    lease = acquire(repo, registration)
    before = service.capture(lease, phase="before")
    service.mark_running(lease)
    service.stop(lease)
    archived = service.capture(lease, phase="after")
    assert repo.snapshot(lease, "before") == before.archive
    assert repo.snapshot(lease, "after") == archived.archive
    assert before.restore_verified and archived.restore_verified
    with pytest.raises(EnvironmentFenceRejected):
        repo.release(lease)
    service.reset(lease)
    assert state(pg, lease) == ("leased", "reset_complete", None, True)
    service.release(lease)
    assert acquire(repo, registration).generation == lease.generation + 1
    with pg[1]() as session:
        assert session.get(Snapshot, archived.archive.snapshot_id).restore_verified is False
        assert session.get(Lease, lease.lease_id).reset_verified is True
        snapshots = session.scalars(select(Snapshot).where(Snapshot.lease_id == lease.lease_id)).all()
        assert {row.phase for row in snapshots} == {"before", "after"}
        restores = session.scalars(select(Restore).where(Restore.lease_id == lease.lease_id)).all()
        assert len(restores) == 2 and all(row.independent_copy_verified and row.source_unchanged for row in restores)


def test_database_rejects_second_active_lease_and_identity_rewrites(pg, registered):
    repo, registration = registered
    lease = acquire(repo, registration)
    with pytest.raises(IntegrityError), pg[1].begin() as session:
        session.add(Lease(lease_id=uuid4().hex, environment_id=lease.environment_id,
            version_id=lease.version_id, batch_id=lease.batch_id, owner_id="other", generation=2,
            created_at=lease.created_at, expires_at=lease.expires_at, phase="leased", baseline_verified=False, reset_verified=False))
    for table, key, value, assignment in (
        (Lease.__tablename__, "lease_id", lease.lease_id, "expires_at = expires_at + interval '1 second'"),
        (Environment.__tablename__, "environment_id", lease.environment_id, "target_key = 'rebound'"),
    ):
        with pytest.raises(DBAPIError), pg[0].begin() as conn:
            conn.execute(text(f"UPDATE {table} SET {assignment} WHERE {key} = :id"), {"id": value})
        with pytest.raises(DBAPIError), pg[0].begin() as conn:
            conn.execute(text(f"DELETE FROM {table} WHERE {key} = :id"), {"id": value})
    repo.require_live(lease, phases=("leased",))


def test_snapshot_metadata_is_immutable_and_downgrade_refuses_retained_data(pg, registered, monkeypatch):
    repo, registration = registered
    service, _, _ = specimen_service(repo, registration, monkeypatch)
    lease = acquire(repo, registration)
    archived = service.capture(lease, phase="before").archive
    for query in ("UPDATE quality_execution_environment_snapshots SET snapshot_verified = false WHERE snapshot_id = :id",
                  "DELETE FROM quality_execution_environment_snapshots WHERE snapshot_id = :id",
                  "UPDATE quality_execution_snapshot_restores SET verified = false WHERE snapshot_id = :id",
                  "DELETE FROM quality_execution_snapshot_restores WHERE snapshot_id = :id"):
        with pytest.raises(DBAPIError), pg[0].begin() as conn:
            conn.execute(text(query), {"id": archived.snapshot_id})
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0131_execution_environment_lifecycle.py"
    spec = importlib.util.spec_from_file_location("lifecycle_migration_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with pytest.raises(RuntimeError, match="retained"), pg[0].begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()
    assert repo.snapshot(lease, "before") == archived


def test_registration_cannot_be_rebound_or_cross_project(registered):
    repo, registration = registered
    repo.register(registration)
    with pytest.raises(EnvironmentLifecycleInvalid):
        repo.register(replace(registration, inventory_hash="sha256:" + "b" * 64))
    with pytest.raises(EnvironmentLeaseUnavailable):
        acquire(repo, registration, project_id="other")
    with pytest.raises(EnvironmentLeaseUnavailable):
        acquire(repo, replace(registration, environment_id="unregistered"))


def test_database_allows_before_and_after_but_rejects_duplicate_phase(pg, registered, monkeypatch):
    repo, registration = registered
    service, _, _ = specimen_service(repo, registration, monkeypatch)
    lease = acquire(repo, registration)
    before = service.capture(lease, phase="before").archive
    duplicate = replace(before, snapshot_id=uuid4().hex, object_key="private/test-duplicate-" + uuid4().hex)
    with pytest.raises(IntegrityError), pg[1].begin() as session:
        session.add(Snapshot(**asdict(duplicate)))
    service.mark_running(lease)
    service.stop(lease)
    after = service.capture(lease, phase="after").archive
    assert before.lease_id == after.lease_id and before.generation == after.generation
    assert before.snapshot_id != after.snapshot_id and before.object_key != after.object_key
    assert repo.snapshot(lease, "before") == before and repo.snapshot(lease, "after") == after


@pytest.mark.parametrize("fault", ["baseline", "before_restore", "after_restore"])
def test_unproved_baseline_or_independent_copy_never_admits_running_or_reset(pg, registered, monkeypatch, fault):
    repo, registration = registered
    service, target, _ = specimen_service(repo, registration, monkeypatch)
    lease = acquire(repo, registration)
    with pytest.raises(EnvironmentFenceRejected):
        service.mark_running(lease)
    phase = "before"
    if fault == "after_restore":
        service.capture(lease, phase="before")
        service.mark_running(lease)
        service.stop(lease)
        phase = "after"
    if fault == "baseline":
        target.clean = False
    else:
        target.restored = False
    with pytest.raises(EnvironmentOperationFailed):
        service.capture(lease, phase=phase)
    assert state(pg, lease)[0] == "quarantined" and not state(pg, lease)[3]
    with pg[1]() as session:
        snapshots = session.scalars(select(Snapshot).where(Snapshot.lease_id == lease.lease_id)).all()
        restores = session.scalars(select(Restore).where(Restore.lease_id == lease.lease_id)).all()
        assert len(snapshots) == {"baseline": 0, "before_restore": 1, "after_restore": 2}[fault]
        assert len(restores) == (1 if fault == "after_restore" else 0)
    assert "reset" not in target.calls
