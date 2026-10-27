"""Real PG lease clocks/transactions with explicit parent and ACL specimens.

The minimal parent is not an original RunPlan, native execution, or source ACL
proof. These tests isolate lease timing without weakening production verifiers.
"""
from contextlib import contextmanager
from dataclasses import asdict
import importlib
import logging
from types import SimpleNamespace
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from apps.api.app.application.quality_loop.http_fixture_work import HttpFixtureWorkLost
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.infrastructure.persistence.http_fixture_work_models import HttpFixtureWorkLeaseRecord as Lease
from apps.api.app.infrastructure.persistence.http_fixture_work_repository import PostgresHttpFixtureWorkRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_http_fixture_journal_access import saved_inputs


@pytest.fixture
def clock_work(monkeypatch):
    module = importlib.import_module("apps.api.app.infrastructure.persistence.http_fixture_work_repository")
    migration = importlib.import_module("apps.api.migrations.versions.0109_http_fixture_work")
    _access, scope, _manifest, _view = saved_inputs()
    with session_scope() as outer:
        connection = outer.connection()
        assert connection.dialect.name == "postgresql"
        assert outer.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        namespace = "fixture_clock_" + uuid4().hex
        connection.execute(text(f'CREATE SCHEMA "{namespace}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{namespace}", public'))
        connection.execute(text("""
            CREATE TABLE quality_run_plans (
                project_id text NOT NULL, run_plan_id text NOT NULL,
                artifact_hash text NOT NULL, plan_digest text NOT NULL,
                image_revision_id text NOT NULL, manifest_id text NOT NULL,
                UNIQUE (project_id, run_plan_id, artifact_hash, plan_digest, image_revision_id, manifest_id)
            )
        """))
        connection.execute(text("""
            CREATE TABLE quality_http_fixture_dispatches (
                project_id text NOT NULL, claim_id text NOT NULL,
                UNIQUE (project_id, claim_id)
            )
        """))
        parent = {"project_id": scope.project_id, "run_plan_id": "clock-parent-specimen",
            "run_plan_artifact_hash": "sha256:" + "1" * 64, "plan_digest": scope.parent_digest}
        connection.execute(text("""
            INSERT INTO quality_run_plans VALUES
                (:project_id, :run_plan_id, :run_plan_artifact_hash, :plan_digest, 'clock-image', 'clock-manifest')
        """), parent)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        @contextmanager
        def isolated_transaction():
            with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                with session.begin():
                    yield session

        monkeypatch.setattr(module, "session_scope", isolated_transaction)

        def now():
            return connection.scalar(select(func.clock_timestamp()))

        def pause(seconds):
            connection.execute(text("SELECT pg_sleep(:seconds)"), {"seconds": seconds})

        class AccessSpecimen:
            def __init__(self):
                self.calls = 0
                self.delayed_call = None
                self.delay = 0
                self.finished = []
                self.changed_call = None

            def require_scope(self, value):
                assert value == scope
                self.calls += 1
                if self.calls == self.delayed_call:
                    pause(self.delay)
                self.finished.append(now())
                return {**parent, "plan_digest": "sha256:" + "2" * 64} if self.calls == self.changed_call else dict(parent)

        class AuthoritySpecimen:
            def __init__(self):
                self.calls = 0
                self.delayed_call = None
                self.delay = 0
                self.revoked_call = None
                self.finished = []

            def __call__(self):
                self.calls += 1
                if self.calls == self.delayed_call:
                    pause(self.delay)
                if self.calls == self.revoked_call:
                    raise PermissionError("explicit current authority revoked")
                self.finished.append(now())

        access, authority = AccessSpecimen(), AuthoritySpecimen()

        def parent_specimen(session, value):
            if value != parent:
                raise HttpFixtureInvalid("clock specimen parent changed")
            row = session.execute(text("SELECT image_revision_id, manifest_id FROM quality_run_plans WHERE project_id = :project_id"),
                {"project_id": scope.project_id}).one()
            return SimpleNamespace(image_revision_id=row.image_revision_id, manifest_id=row.manifest_id)

        def lock_specimen(session, value):
            parent_specimen(session, value)
            session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": namespace})

        journal = SimpleNamespace(access=access, actor_id="clock-actor-specimen",
            _parent=parent_specimen, _lock=lock_specimen)
        repository = PostgresHttpFixtureWorkRepository(journal)
        monkeypatch.setattr(repository, "_actor_current", lambda *_args: None)

        def stored(lease):
            with isolated_transaction() as session:
                row = session.get(Lease, lease.work_id)
                return None if row is None else {column.name: getattr(row, column.name) for column in Lease.__table__.columns}

        yield SimpleNamespace(module=module, repository=repository, scope=scope, access=access,
            authority=authority, now=now, stored=stored, pause=pause, connection=connection)
        connection.execute(text(f'DROP SCHEMA "{namespace}" CASCADE'))


@pytest.mark.parametrize("slow_guard", ["original_scope", "current_authority"])
def test_acquisition_starts_pg_lease_after_all_slow_guards(clock_work, monkeypatch, slow_guard):
    v = clock_work
    monkeypatch.setattr(v.module, "FIXTURE_WORK_LEASE_SECONDS", 1)
    guard = v.access if slow_guard == "original_scope" else v.authority
    guard.delayed_call, guard.delay = (2 if slow_guard == "original_scope" else 3), 1.1
    lease = v.repository.acquire(v.scope, "setup", "clock-worker", require_current=v.authority)
    row = v.stored(lease)
    assert row["acquired_at"] >= max(*v.access.finished, *v.authority.finished)
    assert (row["expires_at"] - v.now()).total_seconds() > 0.8
    assert row["scope"] == asdict(v.scope) and row["epoch"] == 1
    v.repository.require(lease)


@pytest.mark.parametrize("slow_guard", ["original_scope", "current_authority"])
def test_renewal_stamps_pg_clock_only_after_all_slow_guards(clock_work, monkeypatch, slow_guard):
    v = clock_work
    monkeypatch.setattr(v.module, "FIXTURE_WORK_LEASE_SECONDS", 3)
    lease = v.repository.acquire(v.scope, "setup", "clock-worker", require_current=v.authority)
    before = v.stored(lease)
    guard = v.access if slow_guard == "original_scope" else v.authority
    guard.delayed_call, guard.delay = guard.calls + 2, 1.1
    v.repository.renew(lease, require_current=v.authority)
    row = v.stored(lease)
    assert row["renewed_at"] >= max(*v.access.finished, *v.authority.finished)
    assert (row["expires_at"] - v.now()).total_seconds() > 2.7
    assert row["acquired_at"] == before["acquired_at"] and row["epoch"] == before["epoch"]
    v.repository.require(lease)


def test_expiry_during_renewal_cannot_revive_original_owner(clock_work, monkeypatch):
    v = clock_work
    monkeypatch.setattr(v.module, "FIXTURE_WORK_LEASE_SECONDS", 1)
    lease = v.repository.acquire(v.scope, "setup", "clock-worker", require_current=v.authority)
    before = v.stored(lease)
    v.access.delayed_call, v.access.delay = v.access.calls + 2, 1.1
    with pytest.raises(HttpFixtureWorkLost):
        v.repository.renew(lease, require_current=v.authority)
    assert v.stored(lease) == before
    with pytest.raises(HttpFixtureWorkLost):
        v.repository.require(lease)


def test_lease_operations_keep_fresh_authority_inside_one_read_session(clock_work, monkeypatch):
    v = clock_work
    sessions, original_reads, authority_reads = [], [], []
    active = None

    @contextmanager
    def read_session():
        nonlocal active
        assert active is None
        current = {"sequence": len(sessions), "closed": False}
        sessions.append(current)
        active = current
        try:
            yield
        finally:
            current["closed"] = True
            active = None

    original_scope = v.access.require_scope

    def checked_scope(scope):
        assert active is not None and not active["closed"]
        original_reads.append(active["sequence"])
        return original_scope(scope)

    def current():
        assert active is not None and not active["closed"]
        authority_reads.append(active["sequence"])
        v.authority()

    monkeypatch.setattr(v.access, "verified_read_session", read_session, raising=False)
    monkeypatch.setattr(v.access, "require_scope", checked_scope)
    lease = v.repository.acquire(v.scope, "setup", "scoped-clock-worker", require_current=current)
    before = v.stored(lease)
    v.repository.require(lease)
    v.repository.renew(lease, require_current=current)
    renewed = v.stored(lease)
    assert original_reads == [0, 0, 1, 2, 2]
    assert authority_reads == [0, 0, 0, 2, 2]
    assert active is None and all(value["closed"] for value in sessions)
    assert before["epoch"] == renewed["epoch"] == 1
    assert renewed["acquired_at"] == before["acquired_at"] and renewed["renewed_at"] >= before["renewed_at"]
    assert (renewed["expires_at"] - renewed["renewed_at"]).total_seconds() == 90

    # The final fresh guard still rolls back a renewal; immutable proof reuse
    # does not turn the beginning of the operation into lasting authority.
    v.authority.revoked_call = v.authority.calls + 2
    with pytest.raises(PermissionError):
        v.repository.renew(lease, require_current=current)
    assert v.stored(lease) == renewed
    assert active is None and all(value["closed"] for value in sessions)


@pytest.mark.parametrize("operation", ["acquire", "renew"])
def test_revocation_in_final_guard_rolls_back_lease_changes(clock_work, operation):
    v = clock_work
    if operation == "acquire":
        v.authority.revoked_call = 3
        with pytest.raises(PermissionError, match="revoked"):
            v.repository.acquire(v.scope, "setup", "clock-worker", require_current=v.authority)
        assert v.connection.scalar(text("SELECT count(*) FROM quality_http_fixture_work_leases")) == 0
    else:
        lease = v.repository.acquire(v.scope, "setup", "clock-worker", require_current=v.authority)
        before = v.stored(lease)
        v.authority.revoked_call = v.authority.calls + 2
        with pytest.raises(PermissionError, match="revoked"):
            v.repository.renew(lease, require_current=v.authority)
        assert v.stored(lease) == before


@pytest.mark.parametrize("operation", ["acquire", "renew"])
def test_revalidation_cannot_swap_original_parent_pin(clock_work, operation):
    v = clock_work
    lease = None
    if operation == "renew":
        lease = v.repository.acquire(v.scope, "setup", "clock-worker", require_current=v.authority)
    before = v.stored(lease) if lease is not None else None
    v.access.changed_call = v.access.calls + 2
    with pytest.raises(HttpFixtureInvalid):
        if lease is None:
            v.repository.acquire(v.scope, "setup", "clock-worker", require_current=v.authority)
        else:
            v.repository.renew(lease, require_current=v.authority)
    if lease is None:
        assert v.connection.scalar(text("SELECT count(*) FROM quality_http_fixture_work_leases")) == 0
    else:
        assert v.stored(lease) == before


@pytest.mark.parametrize("operation,phase", [
    ("acquire", "work_initial_authority"), ("acquire", "work_original_scope"),
    ("acquire", "work_transaction_lock"), ("acquire", "work_locked_authority"),
    ("acquire", "work_registered_parent"), ("acquire", "work_final_scope"),
    ("acquire", "work_final_authority"), ("renew", "work_initial_authority"),
    ("renew", "work_original_scope"), ("renew", "work_transaction_lock"),
    ("renew", "work_live_lease"), ("renew", "work_final_scope"),
    ("renew", "work_final_authority"), ("require", "work_original_scope"),
    ("require", "work_live_lease"),
])
def test_work_diagnostics_locate_the_original_guard_without_leaking_or_committing(
        clock_work, monkeypatch, caplog, operation, phase):
    v = clock_work
    lease = None if operation == "acquire" else v.repository.acquire(
        v.scope, "setup", "diagnostic-owner", require_current=v.authority)
    before = v.stored(lease) if lease is not None else None
    caplog.clear()
    caplog.set_level(logging.INFO, logger="apps.api.app.application.quality_loop.http_fixture_diagnostics")
    private = "private://original-source?api_key=do-not-log&sql=SELECT-secret"
    error = PermissionError(private)

    def fail(*_args, **_options):
        raise error

    if phase in {"work_initial_authority", "work_locked_authority", "work_final_authority"}:
        fail_at = {"work_initial_authority": 1, "work_locked_authority": 2,
            "work_final_authority": 3 if operation == "acquire" else 2}[phase]
        original = v.authority
        seen = 0

        def authority():
            nonlocal seen
            seen += 1
            if seen == fail_at:
                raise error
            original()
    else:
        authority = v.authority
        if phase in {"work_original_scope", "work_final_scope"}:
            original_scope = v.access.require_scope
            seen = 0

            def scope(value):
                nonlocal seen
                seen += 1
                if seen == (1 if phase == "work_original_scope" else 2):
                    raise error
                return original_scope(value)
            monkeypatch.setattr(v.access, "require_scope", scope)
        elif phase == "work_transaction_lock":
            monkeypatch.setattr(v.repository.journal, "_lock", fail)
        else:
            monkeypatch.setattr(v.repository, "_pins" if phase == "work_registered_parent" else "_live", fail)

    with pytest.raises(PermissionError) as raised:
        if operation == "acquire":
            v.repository.acquire(v.scope, "setup", "diagnostic-owner", require_current=authority)
        elif operation == "renew":
            v.repository.renew(lease, require_current=authority)
        else:
            v.repository.require(lease)
    assert raised.value is error
    failures = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert [record.args[:2] for record in failures] == [(phase, "PermissionError"),
        ("work_" + operation, "PermissionError")]
    assert private not in caplog.text and all(record.exc_info is None for record in caplog.records)
    if lease is None:
        assert v.connection.scalar(text("SELECT count(*) FROM quality_http_fixture_work_leases")) == 0
    else:
        assert v.stored(lease) == before
