"""Private work contract specimens, not canonical or business execution evidence."""
import asyncio
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.http_fixture_work import (
    HttpFixtureWorkLease, HttpFixtureWorkLost, fixture_work_digest, fixture_work_identity, run_with_http_fixture_work,
)
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.infrastructure.persistence.http_fixture_work_models import (
    HttpFixtureDispatchOwnershipRecord as Ownership, HttpFixtureWorkLeaseRecord as Lease,
)
from apps.api.app.infrastructure.persistence.http_fixture_work_repository import verify_dispatch_ownership
from apps.api.tests.test_http_fixture_journal_access import saved_inputs


def work(operation="setup", **changes):
    _access, scope, _recipe, _view = saved_inputs()
    return HttpFixtureWorkLease(**{**dict(scope=scope, operation=operation, owner_id="worker-original", epoch=1,
        request_digest=fixture_work_digest(scope, operation)), **changes})


@pytest.mark.parametrize("operation,phase", [("setup", "setup"), ("cleanup", "cleanup:session")])
def test_phase_ownership_is_specific_without_granting_execution_authority(operation, phase):
    lease = work(operation)
    lease.require_phase(lease.scope, phase)
    assert lease.work_id == fixture_work_identity(lease.scope, operation)
    assert not hasattr(lease, "execution_authorized")


@pytest.mark.parametrize("field,value", [("epoch", True), ("epoch", 0), ("epoch", 2147483648),
    ("owner_id", ""), ("owner_id", " "), ("owner_id", "bad\nowner"), ("owner_id", "x" * 129),
    ("scope", None), ("operation", []), ("request_digest", "sha256:" + "0" * 64)])
def test_lease_rejects_invalid_owner_epoch_or_rebound_digest(field, value):
    with pytest.raises(HttpFixtureInvalid): work(**{field: value})


@pytest.mark.parametrize("phase", ["cleanup:session", "another", None, "cleanup:"])
def test_setup_owner_cannot_dispatch_cleanup_or_unscoped_requests(phase):
    lease = work()
    with pytest.raises(HttpFixtureWorkLost): lease.require_phase(lease.scope, phase)


@pytest.mark.parametrize("field", ["timeout_ms", "artifact_hash", "inventory_hash", "parent_digest", "environment_id"])
def test_mutating_execution_pins_does_not_create_a_new_work_identity(field):
    lease = work()
    changed = replace(lease.scope, **{field: 11000 if field == "timeout_ms" else
        acceptance_digest("changed") if field.endswith(("hash", "digest")) else "another"})
    assert fixture_work_identity(changed, "setup") == lease.work_id
    assert fixture_work_digest(changed, "setup") != lease.request_digest
    with pytest.raises(HttpFixtureWorkLost): lease.require_phase(changed, "setup")


def ownership_session():
    lease = work()
    pin = {"work_id": lease.work_id, "owner_id": lease.owner_id, "epoch": lease.epoch, "request_digest": lease.request_digest}
    dispatch = {"schema": "nasus.http-fixture-dispatch.v2", "claim_id": "original", "project_id": lease.scope.project_id,
        "scope": asdict(lease.scope), "phase": "setup", "actor_id": "actor", "work_ownership": pin}
    value = {"schema": "nasus.http-fixture-dispatch-ownership.v1", "claim_id": "original",
        "project_id": lease.scope.project_id, **pin, "dispatch_digest": acceptance_digest(dispatch),
        "recorded_at": "original-time", "execution_authorized": False, "business_coverage_verified": False}
    owner = Ownership(**{key: value[key] for key in ("claim_id", "project_id", "work_id", "owner_id", "epoch", "request_digest",
        "dispatch_digest", "recorded_at")}, payload=value, content_hash=acceptance_digest(value))
    row = Lease(work_id=lease.work_id, scope=asdict(lease.scope), scope_digest=lease.scope.digest,
        request_digest=lease.request_digest, actor_id="actor", epoch=2, owner_id="replacement")
    rows = {Ownership: owner, Lease: row}
    return SimpleNamespace(get=lambda model, _id: rows.get(model)), dispatch, rows


def test_historical_original_ownership_is_not_replaced_by_current_owner():
    session, dispatch, _rows = ownership_session()
    result = verify_dispatch_ownership(session, dispatch)
    assert result["owner_id"] == "worker-original" and result["epoch"] == 1


@pytest.mark.parametrize("mutation", ["missing", "missing_lease", "changed_payload", "changed_column", "foreign_scope", "future_epoch"])
def test_owned_history_cannot_be_downgraded_rebound_or_silently_repaired(mutation):
    session, dispatch, rows = ownership_session()
    owner = rows[Ownership]
    if mutation == "missing": rows.pop(Ownership)
    elif mutation == "missing_lease": rows.pop(Lease)
    elif mutation == "changed_payload": owner.payload = {**owner.payload, "epoch": 3}
    elif mutation == "changed_column": owner.owner_id = "replacement"
    elif mutation == "foreign_scope": rows[Lease].scope = {**rows[Lease].scope, "project_id": "foreign"}
    elif mutation == "future_epoch": rows[Lease].epoch = 0
    before = deepcopy(dispatch)
    with pytest.raises(HttpFixtureInvalid): verify_dispatch_ownership(session, dispatch)
    assert dispatch == before


def test_legacy_private_dispatch_does_not_acquire_fabricated_worker_history():
    session, dispatch, rows = ownership_session()
    rows.pop(Ownership)
    dispatch.pop("work_ownership")
    dispatch["schema"] = "nasus.http-fixture-dispatch.v1"
    assert verify_dispatch_ownership(session, dispatch) is None


@pytest.mark.parametrize("location", ["ownership", "dispatch"])
def test_rehashed_boolean_epoch_cannot_replace_original_numeric_worker_fencing(location):
    session, dispatch, rows = ownership_session()
    owner = rows[Ownership]
    if location == "ownership": owner.payload["epoch"] = True
    else: dispatch["work_ownership"]["epoch"] = True
    owner.payload["dispatch_digest"] = acceptance_digest(dispatch)
    owner.dispatch_digest = owner.payload["dispatch_digest"]
    owner.content_hash = acceptance_digest(owner.payload)
    with pytest.raises(HttpFixtureInvalid): verify_dispatch_ownership(session, dispatch)


def test_reused_async_lifecycle_renews_owner_and_passes_current_fence():
    lease = work()
    async def exercise():
        calls = []
        repository = SimpleNamespace(require=lambda lease: calls.append(("check", lease.epoch)),
            renew=lambda lease, require_current: (require_current(), calls.append(("renew", lease.epoch))))
        async def execute(require_work):
            await asyncio.sleep(0.06)
            require_work()
            return "original-result"
        result = await run_with_http_fixture_work(repository, lease, execute,
            require_current=lambda: calls.append(("current", 1)), renew_seconds=0.01)
        assert result == "original-result" and any(item[0] == "renew" for item in calls)
        assert calls.count(("check", 1)) == 2
    asyncio.run(exercise())


def test_lost_heartbeat_cancels_adapter_without_invoking_another_attempt():
    lease = work()
    async def exercise():
        attempts, cancelled = [], []
        def renew(_lease, require_current): raise HttpFixtureWorkLost("explicit lease takeover")
        repository = SimpleNamespace(require=lambda _lease: None, renew=renew)
        async def execute(_require_work):
            attempts.append("original")
            try: await asyncio.sleep(10)
            finally: cancelled.append(True)
        with pytest.raises(HttpFixtureWorkLost):
            await run_with_http_fixture_work(repository, lease, execute, require_current=lambda: None, renew_seconds=0.01)
        assert attempts == ["original"] and cancelled == [True]
    asyncio.run(exercise())
