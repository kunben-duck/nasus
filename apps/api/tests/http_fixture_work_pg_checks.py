"""PG ownership checks with an explicit frozen parent-reader/Runner specimen.

The caller first verifies the real API/S3 parent. This isolated reader does not
prove current source ACLs or canonical execution consent, and never runs exweb.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import importlib
from types import SimpleNamespace
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from apps.api.app.application.quality_loop.http_fixture_journal_access import SavedRunPlanHttpFixtureAccess
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureLifecycleApplicationService, HttpFixtureOutcomeUnknown
from apps.api.app.application.quality_loop.http_fixture_work import HttpFixtureWorkBusy, HttpFixtureWorkLost
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.infrastructure.persistence.http_fixture_journal_models import HttpFixtureDispatchRecord as Dispatch, HttpFixtureResultRecord as Result
from apps.api.app.infrastructure.persistence.http_fixture_journal_repository import PostgresHttpFixtureDispatchJournal
from apps.api.app.infrastructure.persistence.http_fixture_work_models import HttpFixtureWorkLeaseRecord as Lease, HttpFixtureDispatchOwnershipRecord as Ownership
from apps.api.app.infrastructure.persistence.http_fixture_work_repository import PostgresHttpFixtureWorkRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.runner.http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from apps.api.tests.test_http_fixtures import Runner
from apps.api.tests.test_http_bindings import specimen


def verify_private_pg_fixture_work(parent, recipe, scope, view, artifacts, actor, monkeypatch):
    frozen = SimpleNamespace(read=lambda _project, _id: deepcopy(view))
    access = SavedRunPlanHttpFixtureAccess(frozen, parent, recipe)
    journal = PostgresHttpFixtureDispatchJournal(access, artifacts, actor_id=actor.id)
    repository = PostgresHttpFixtureWorkRepository(journal)
    scope = replace(scope, attempt_id="worker-" + uuid4().hex)
    lease = repository.acquire(scope, "setup", "worker-a", require_current=lambda: None)
    repository.require(lease)
    repository.renew(lease, require_current=lambda: None)
    with pytest.raises(HttpFixtureWorkBusy): repository.acquire(scope, "setup", "worker-b", require_current=lambda: None)
    with pytest.raises(HttpFixtureInvalid):
        repository.acquire(replace(scope, timeout_ms=11000), "setup", "worker-b", require_current=lambda: None)
    with session_scope() as session:
        row = session.get(Lease, lease.work_id)
        assert row.epoch == 1 and row.owner_id == "worker-a" and row.expires_at > row.renewed_at >= row.acquired_at

    def fenced(value):
        return PostgresHttpFixtureDispatchJournal(access, artifacts, actor_id=actor.id, work_fence=repository.fence(value))

    command = access.command(scope, "setup")
    owned = fenced(lease)
    owned.claim(scope, "setup", command, require_current=lambda: repository.require(lease))
    runner = Runner()
    runner.payload = lambda current: specimen(current, states=["passed", "passed", "passed", "failed"], status="failed")
    execution = runner.execute_owned_http(command, environment_id=scope.environment_id,
        artifact_hash=scope.artifact_hash, inventory_hash=scope.inventory_hash, require_work=lambda: repository.require(lease))
    owned.complete(scope, "setup", command, execution, require_current=lambda: repository.require(lease))
    owned.complete(scope, "setup", command, execution, require_current=lambda: repository.require(lease))
    claim = owned._identity(scope, "setup")
    with session_scope() as session:
        dispatch, ownership, result = session.get(Dispatch, claim), session.get(Ownership, claim), session.get(Result, claim)
        assert dispatch.payload["schema"] == "nasus.http-fixture-dispatch.v2"
        assert ownership.owner_id == "worker-a" and ownership.epoch == 1 and result is not None
        assert result.status == "failed" and command.steps[-1]["value_json"] == '"EXPLICIT_NEGATIVE_CONTROL"'
        assert dispatch.payload["execution_authorized"] is False and ownership.payload["business_coverage_verified"] is False
    with pytest.raises(HttpFixtureInvalid):
        journal.complete(scope, "setup", command, execution, require_current=lambda: None)
    assert journal.inspect(scope, "setup").execution.result_body == execution.result_body

    for statement in ("DELETE FROM quality_http_fixture_dispatch_ownership WHERE claim_id = :id",
            "UPDATE quality_http_fixture_dispatch_ownership SET epoch = epoch + 1 WHERE claim_id = :id",
            "UPDATE quality_http_fixture_work_leases SET scope_digest = 'changed' WHERE work_id = :id",
            "UPDATE quality_http_fixture_work_leases SET owner_id = 'replacement' WHERE work_id = :id",
            "DELETE FROM quality_http_fixture_work_leases WHERE work_id = :id"):
        with pytest.raises(DBAPIError, match="Original fixture|immutable|append-only|mutation"):
            with session_scope() as session:
                session.execute(text(statement), {"id": claim if "ownership" in statement else lease.work_id})

    # Failure after both original dispatch and ownership were staged rolls back
    # all journal facts/events, but never erases the durable worker lease.
    failed_scope = replace(scope, attempt_id="worker-rollback-" + uuid4().hex)
    failed_lease = repository.acquire(failed_scope, "setup", "worker-a", require_current=lambda: None)
    failed = fenced(failed_lease)
    original_claim = failed.work_fence.claim
    def fail_ownership_commit(session, dispatch):
        original_claim(session, dispatch)
        raise RuntimeError("explicit ownership commit fault")
    monkeypatch.setattr(failed.work_fence, "claim", fail_ownership_commit)
    with pytest.raises(RuntimeError, match="explicit ownership"):
        failed.claim(failed_scope, "setup", access.command(failed_scope, "setup"), require_current=lambda: repository.require(failed_lease))
    with session_scope() as session:
        failed_id = failed._identity(failed_scope, "setup")
        assert session.get(Dispatch, failed_id) is None and session.get(Ownership, failed_id) is None
        assert session.get(Lease, failed_lease.work_id) is not None

    # Use the real PG clock and a shorter test-only lease, not altered historical
    # dispatch timestamps, to exercise takeover and reject a delayed old result.
    with monkeypatch.context() as patch:
        module = importlib.import_module("apps.api.app.infrastructure.persistence.http_fixture_work_repository")
        patch.setattr(module, "FIXTURE_WORK_LEASE_SECONDS", 2)
        unknown_scope = replace(scope, attempt_id="worker-unknown-" + uuid4().hex)
        first = repository.acquire(unknown_scope, "setup", "worker-old", require_current=lambda: None)
        original = fenced(first)
        request = access.command(unknown_scope, "setup")
        original.claim(unknown_scope, "setup", request, require_current=lambda: repository.require(first))
    native = runner.execute_owned_http(request, environment_id=unknown_scope.environment_id,
        artifact_hash=unknown_scope.artifact_hash, inventory_hash=unknown_scope.inventory_hash, require_work=lambda: None)
    with session_scope() as session: session.execute(text("SELECT pg_sleep(2.05)"))
    second = repository.acquire(unknown_scope, "setup", "worker-new", require_current=lambda: None)
    assert second.epoch == first.epoch + 1
    with pytest.raises(HttpFixtureWorkLost): repository.require(first)
    with pytest.raises(HttpFixtureWorkLost): repository.renew(first, require_current=lambda: None)
    with pytest.raises(HttpFixtureWorkLost):
        original.complete(unknown_scope, "setup", request, native, require_current=lambda: repository.require(first))
    replacement = fenced(second)
    with pytest.raises(HttpFixtureWorkLost):
        replacement.complete(unknown_scope, "setup", request, native, require_current=lambda: repository.require(second))
    calls = len(runner.commands)
    lifecycle = HttpFixtureLifecycleApplicationService(runner, replacement, OwnedHttpFixtureObservationVerifier())
    with pytest.raises(HttpFixtureOutcomeUnknown):
        lifecycle.prepare(unknown_scope, recipe, require_work=lambda: repository.require(second))
    assert len(runner.commands) == calls and replacement.inspect(unknown_scope, "setup").execution is None

    racing_scope = replace(scope, attempt_id="worker-race-" + uuid4().hex)
    def compete(owner):
        try: return repository.acquire(racing_scope, "setup", owner, require_current=lambda: None)
        except HttpFixtureWorkBusy: return "busy"
    with ThreadPoolExecutor(max_workers=2) as workers:
        winners = list(workers.map(compete, ["worker-a", "worker-b"]))
    assert sum(value == "busy" for value in winners) == 1
    with session_scope() as session:
        assert len(session.scalars(select(Lease).where(Lease.attempt_id == racing_scope.attempt_id)).all()) == 1

    migration = importlib.import_module("apps.api.migrations.versions.0109_http_fixture_work")
    with session_scope() as session:
        with Operations.context(MigrationContext.configure(session.connection())):
            with pytest.raises(RuntimeError, match="Cannot discard populated original fixture work history"):
                migration.downgrade()
        assert session.get(Ownership, claim) is not None and session.get(Result, claim) is not None
