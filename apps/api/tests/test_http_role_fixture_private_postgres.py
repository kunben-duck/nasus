"""Disposable PostgreSQL only, through scripts/test-api-postgres.py. No target I/O."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from threading import Barrier, Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from apps.api.app.application.quality_loop.http_role_credentials import (
    HttpRoleCredential, HttpRoleCredentialInvalid, HttpRoleCredentialService, HttpRoleFixtureLifecycleService,
    HttpRoleFixtureOutcomeUnknown, HttpRoleFixturePhaseRecord, HttpRoleResourceBinding, NativeHttpRoleFixtureResult,
)
from apps.api.app.domain.quality_loop.http_execution_scope import HttpExecutionScope
from apps.api.app.domain.quality_loop.http_role_fixtures import HttpRoleFixtureInvalid, http_role_fixture_manifest_digest
from apps.api.app.infrastructure.persistence.http_role_fixture_models import (
    HttpRoleCredentialEnvelopeRecord as Envelope, HttpRoleFixtureClaimRecord as Claim,
    HttpRoleFixtureResultRecord as Result,
)
from apps.api.app.infrastructure.persistence.http_role_fixture_repository import (
    PostgresHttpRoleFixtureJournal, PostgresPrivateHttpRoleCredentialEnvelopes,
)
from apps.api.app.infrastructure.runner.execution_vault import ExecutionEnvelopeCipher
from apps.api.app.infrastructure.storage.http_role_credentials import EncryptedHttpRoleCredentialStore
from apps.api.tests.test_http_role_credentials import AUTHOR_SECRET, Authority, assert_redacted
from apps.api.tests.test_http_role_fixture_lifecycle import NativeAdapter
from apps.api.tests.test_http_role_fixtures_v2 import role_manifest


TABLES = (Envelope.__tablename__, Claim.__tablename__, Result.__tablename__)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(body):
    return "sha256:" + hashlib.sha256(body).hexdigest()


@pytest.fixture(scope="module")
def pg():
    connection = os.environ.get("NASUS_TEST_DATABASE_URL")
    if not connection:
        pytest.skip("requires scripts/test-api-postgres.py disposable PostgreSQL harness")
    url = make_url(connection)
    if (url.get_backend_name() != "postgresql" or url.host not in {"localhost", "127.0.0.1", "::1"}
            or not (url.database or "").startswith("nasus_test_")
            or connection != os.environ.get("NASUS_DATABASE_URL")):
        pytest.fail("refusing private role writes outside the isolated PostgreSQL harness")
    engine = create_engine(url, hide_parameters=True)
    try:
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT current_database()")) == url.database
            assert set(inspect(conn).get_table_names()) >= set(TABLES)
        yield engine, sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()


class TransactionGuard:
    """Synthetic current authority; proves callbacks share the actual transaction."""
    def __init__(self):
        self.calls, self.sessions = 0, []
        self.fail_at = None
        self.denied = False

    def __call__(self, session):
        assert session.in_transaction()
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        self.calls += 1
        self.sessions.append(session)
        if self.denied or self.calls == self.fail_at:
            raise PermissionError(AUTHOR_SECRET)


@pytest.fixture
def state(pg):
    guard = TransactionGuard()
    scope = HttpExecutionScope("project", "version", "batch-" + uuid4().hex, "case", "environment", 1,
        "sha256:" + "a" * 64, (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat())
    backend = PostgresPrivateHttpRoleCredentialEnvelopes(pg[1], transaction_guard=guard)
    journal = PostgresHttpRoleFixtureJournal(pg[1], transaction_guard=guard)
    record = HttpRoleFixturePhaseRecord(scope, http_role_fixture_manifest_digest(role_manifest()), "setup")
    result = NativeHttpRoleFixtureResult("succeeded", "sha256:" + "c" * 64,
        (HttpRoleResourceBinding("article", "original-article"),))
    cipher = ExecutionEnvelopeCipher(b"a" * 32, "key-1")
    key = "private-http-role-credentials/" + uuid4().hex + uuid4().hex
    envelope = canonical(cipher.seal(HttpRoleCredential("token", token=AUTHOR_SECRET).private_bytes(),
        scope=scope, purpose="credential", record_id="role-credential:" + "d" * 64))
    return SimpleNamespace(guard=guard, scope=scope, backend=backend, journal=journal, record=record,
        result=result, cipher=cipher, key=key, envelope=envelope, pg=pg)


def current():
    return None


def test_real_ciphertext_readback_and_private_service_handoff(state, caplog):
    item = state
    store = EncryptedHttpRoleCredentialStore(item.cipher, item.backend)
    authority = Authority()
    authority.scope = item.scope
    service = HttpRoleCredentialService(store, authority)
    credential = HttpRoleCredential("token", token=AUTHOR_SECRET)
    service.store(item.scope, role_manifest(), "author", credential)
    reopened = EncryptedHttpRoleCredentialStore(item.cipher,
        PostgresPrivateHttpRoleCredentialEnvelopes(item.pg[1], transaction_guard=item.guard))
    service = HttpRoleCredentialService(reopened, authority)
    assert service.resolve(item.scope, role_manifest(), "author").credential == credential
    assert service.resolve(item.scope, role_manifest(), "anonymous").credential is None
    with item.pg[1]() as session:
        rows = session.scalars(select(Envelope)).all()
        assert rows and all(AUTHOR_SECRET.encode() not in row.envelope for row in rows)
        assert all(row.content_hash == digest(row.envelope) for row in rows)
    assert AUTHOR_SECRET not in caplog.text


def test_envelope_write_once_survives_reopen_and_returns_original_bytes(state):
    item = state
    assert item.backend.put_if_absent(item.key, item.envelope, require_current=current)
    replacement = canonical(item.cipher.seal(b"replacement-private-material", scope=item.scope,
        purpose="credential", record_id="role-credential:" + "d" * 64))
    assert not item.backend.put_if_absent(item.key, replacement, require_current=current)
    reopened = PostgresPrivateHttpRoleCredentialEnvelopes(item.pg[1], transaction_guard=item.guard)
    assert reopened.read(item.key, require_current=current) == item.envelope
    assert reopened.read("private-http-role-credentials/" + "0" * 64, require_current=current) is None
    assert AUTHOR_SECRET.encode() in item.cipher.open(json.loads(item.envelope), scope=item.scope,
        purpose="credential", record_id="role-credential:" + "d" * 64)


@pytest.mark.parametrize("fault", ["plaintext", "extra_secret", "duplicate", "whitespace", "oversized", "nonce",
                                    "ciphertext", "scope", "purpose", "null_schema"])
def test_envelope_adapter_and_database_reject_non_ciphertext_or_invalid_rows(state, fault):
    item = state
    value = json.loads(item.envelope)
    if fault == "extra_secret": value["password"] = AUTHOR_SECRET
    if fault == "nonce": value["nonce"] = "AA=="
    if fault == "ciphertext": value["ciphertext"] = "AA=="
    if fault == "scope": value["aad"]["scope"]["environment_epoch"] = True
    if fault == "purpose": value["aad"]["purpose"] = "evidence"
    if fault == "null_schema": value["aad"]["schema"] = None
    body = canonical(value)
    if fault == "plaintext": body = canonical({"token": AUTHOR_SECRET})
    if fault == "duplicate": body = body.replace(b'"nonce":', b'"nonce":"' + AUTHOR_SECRET.encode() + b'","nonce":')
    if fault == "whitespace": body += b"\n"
    if fault == "oversized": body = b"x" * 32769
    with pytest.raises(HttpRoleCredentialInvalid) as caught:
        item.backend.put_if_absent(item.key, body, require_current=current)
    assert_redacted(caught.value)
    with pytest.raises(IntegrityError), item.pg[1].begin() as session:
        session.add(Envelope(storage_key=item.key, envelope=body, content_hash=digest(body)))
    assert item.backend.read(item.key, require_current=current) is None


def test_concurrent_envelope_writes_have_one_winner(state):
    barrier = Barrier(6)
    def contender(index):
        backend = PostgresPrivateHttpRoleCredentialEnvelopes(state.pg[1], transaction_guard=TransactionGuard())
        body = canonical(state.cipher.seal(str(index).encode(), scope=state.scope,
            purpose="credential", record_id="role-credential:" + "d" * 64))
        barrier.wait(timeout=10)
        return backend.put_if_absent(state.key, body, require_current=current), body
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(contender, range(6)))
    winners = [body for won, body in results if won]
    assert len(winners) == 1
    assert state.backend.read(state.key, require_current=current) == winners[0]


def test_single_claim_and_original_complete_reopen(state):
    item = state
    assert item.journal.inspect(item.scope, "setup") is None
    item.journal.claim(item.record, require_current=current)
    assert item.journal.inspect(item.scope, "setup") == item.record
    with pytest.raises(HttpRoleFixtureOutcomeUnknown): item.journal.claim(item.record, require_current=current)
    complete = replace(item.record, result=item.result)
    item.journal.complete(complete, require_current=current)
    reopened = PostgresHttpRoleFixtureJournal(item.pg[1], transaction_guard=item.guard)
    assert reopened.inspect(item.scope, "setup") == complete
    for changed in (complete, replace(complete, result=replace(item.result, status="failed"))):
        with pytest.raises(HttpRoleFixtureInvalid): reopened.complete(changed, require_current=current)
    assert reopened.inspect(item.scope, "setup") == complete


@pytest.mark.parametrize("field,value", [("project_id", "other"), ("batch_id", "other"), ("case_id", "other"),
    ("version_id", "other"), ("environment_id", "other"), ("environment_epoch", 2),
    ("inventory_hash", "sha256:" + "b" * 64), ("expires_at", "2099-01-01T00:00:00+00:00")])
def test_completion_cannot_rebind_any_scope_field(state, field, value):
    state.journal.claim(state.record, require_current=current)
    changed = replace(state.record, scope=replace(state.scope, **{field: value}), result=state.result)
    with pytest.raises(HttpRoleFixtureInvalid): state.journal.complete(changed, require_current=current)
    assert state.journal.inspect(state.scope, "setup") == state.record


def test_completion_cannot_rebind_manifest_phase_or_expiration_representation(state):
    item = state
    item.journal.claim(item.record, require_current=current)
    complete = replace(item.record, result=item.result)
    alternate_expiry = item.scope.deadline().astimezone(timezone(timedelta(hours=8))).isoformat()
    for changed in (replace(complete, manifest_hash="sha256:" + "f" * 64), replace(complete, phase="cleanup"),
                    replace(complete, scope=replace(item.scope, expires_at=alternate_expiry))):
        with pytest.raises(HttpRoleFixtureInvalid): item.journal.complete(changed, require_current=current)
    assert item.journal.inspect(item.scope, "setup") == item.record


@pytest.mark.parametrize("operation", ["claim", "complete"])
def test_concurrent_phase_writes_have_one_durable_winner(state, operation):
    if operation == "complete": state.journal.claim(state.record, require_current=current)
    barrier = Barrier(6)
    def contender(index):
        journal = PostgresHttpRoleFixtureJournal(state.pg[1], transaction_guard=TransactionGuard())
        record = state.record if operation == "claim" else replace(state.record,
            result=replace(state.result, evidence_digest=digest(str(index).encode())))
        barrier.wait(timeout=10)
        try:
            getattr(journal, operation)(record, require_current=current)
            return record
        except (HttpRoleFixtureInvalid, HttpRoleFixtureOutcomeUnknown):
            return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(contender, range(6)))
    winners = [record for record in results if record is not None]
    assert len(winners) == 1
    assert state.journal.inspect(state.scope, "setup") == winners[0]


@pytest.mark.parametrize("operation", ["envelope", "claim", "complete"])
@pytest.mark.parametrize("guard_kind", ["transaction", "application"])
def test_guard_failure_after_write_rolls_back_without_erasing_claim(state, operation, guard_kind):
    item = state
    if operation == "complete": item.journal.claim(item.record, require_current=current)
    item.guard.calls = 0
    count = 3 if operation == "complete" else 2
    if guard_kind == "transaction": item.guard.fail_at = count
    calls = []
    def application_guard():
        calls.append(True)
        assert item.guard.sessions[-1].in_transaction()
        if guard_kind == "application" and len(calls) == count: raise PermissionError(AUTHOR_SECRET)
    with pytest.raises((HttpRoleCredentialInvalid, HttpRoleFixtureInvalid)) as caught:
        if operation == "envelope": item.backend.put_if_absent(item.key, item.envelope, require_current=application_guard)
        elif operation == "claim": item.journal.claim(item.record, require_current=application_guard)
        else: item.journal.complete(replace(item.record, result=item.result), require_current=application_guard)
    assert_redacted(caught.value)
    item.guard.fail_at = None
    assert item.backend.read(item.key, require_current=current) is None
    assert item.journal.inspect(item.scope, "setup") == (item.record if operation == "complete" else None)


@pytest.mark.parametrize("operation", ["read", "inspect"])
def test_read_guard_revoked_before_return_never_returns_private_state(state, operation):
    state.backend.put_if_absent(state.key, state.envelope, require_current=current)
    state.journal.claim(state.record, require_current=current)
    state.guard.calls, state.guard.fail_at = 0, 2
    with pytest.raises((HttpRoleCredentialInvalid, HttpRoleFixtureInvalid)) as caught:
        if operation == "read": state.backend.read(state.key, require_current=current)
        else: state.journal.inspect(state.scope, "setup")
    assert_redacted(caught.value)


@pytest.mark.parametrize("table,key_column", [(Envelope, "storage_key"), (Claim, "batch_id"), (Result, "batch_id")])
def test_database_rejects_updates_and_deletes_even_without_repository(state, table, key_column):
    item = state
    item.backend.put_if_absent(item.key, item.envelope, require_current=current)
    item.journal.claim(item.record, require_current=current)
    item.journal.complete(replace(item.record, result=item.result), require_current=current)
    key = item.key if table is Envelope else item.scope.batch_id
    for statement in (f"UPDATE {table.__tablename__} SET created_at = clock_timestamp() WHERE {key_column} = :key",
                      f"DELETE FROM {table.__tablename__} WHERE {key_column} = :key",
                      f"TRUNCATE TABLE {table.__tablename__} CASCADE"):
        with pytest.raises(DBAPIError), item.pg[0].begin() as conn:
            conn.execute(text(statement), {"key": key})
    assert item.backend.read(item.key, require_current=current) == item.envelope
    assert item.journal.inspect(item.scope, "setup").result == item.result


def test_database_enforces_hashes_and_original_claim_foreign_key(state):
    item = state
    with pytest.raises(IntegrityError), item.pg[1].begin() as session:
        session.add(Envelope(storage_key=item.key, envelope=item.envelope, content_hash="sha256:" + "0" * 64))
    item.journal.claim(item.record, require_current=current)
    item.journal.complete(replace(item.record, result=item.result), require_current=current)
    with item.pg[1]() as session:
        claim = session.get(Claim, (item.scope.project_id, item.scope.batch_id, item.scope.case_id, "setup"))
        result = session.get(Result, (item.scope.project_id, item.scope.batch_id, item.scope.case_id, "setup"))
        claim_values = {column.name: getattr(claim, column.name) for column in Claim.__table__.columns if column.name != "created_at"}
        result_values = {column.name: getattr(result, column.name) for column in Result.__table__.columns if column.name != "created_at"}
    with pytest.raises(IntegrityError), item.pg[1].begin() as session:
        session.add(Claim(**{**claim_values, "batch_id": "missing-" + uuid4().hex, "claim_hash": "sha256:" + "0" * 64}))
    with pytest.raises(IntegrityError), item.pg[1].begin() as session:
        session.add(Result(**{**result_values, "batch_id": "missing-" + uuid4().hex}))


def test_readback_rejects_consistently_hashed_projection_or_result_ancestry_corruption(state):
    item = state
    item.journal.claim(item.record, require_current=current)
    with item.pg[1]() as session:
        original = session.get(Claim, (item.scope.project_id, item.scope.batch_id, item.scope.case_id, "setup"))
        payload, claim_hash = original.payload, original.claim_hash
    other = replace(item.scope, batch_id="other-" + uuid4().hex)
    with item.pg[1].begin() as session:
        session.add(Claim(project_id=other.project_id, batch_id=other.batch_id, case_id=other.case_id,
            phase="setup", payload=payload, claim_hash=claim_hash))
    with pytest.raises(HttpRoleFixtureInvalid): item.journal.inspect(other, "setup")
    body = canonical({"schema": "nasus.private-http-role-fixture-result.v1", "claim_hash": "sha256:" + "f" * 64,
        "result": {"status": "succeeded", "evidence_digest": item.result.evidence_digest, "resources": []}})
    with item.pg[1].begin() as session:
        session.add(Result(project_id=item.scope.project_id, batch_id=item.scope.batch_id, case_id=item.scope.case_id,
            phase="setup", claim_hash=claim_hash, payload=body, content_hash=digest(body)))
    with pytest.raises(HttpRoleFixtureInvalid): item.journal.inspect(item.scope, "setup")


def test_native_unknown_write_survives_pg_reopen_without_resend(state):
    item = state
    authority = Authority()
    authority.scope = item.scope
    credentials = HttpRoleCredentialService(EncryptedHttpRoleCredentialStore(item.cipher, item.backend), authority)
    native = NativeAdapter()
    native.failure = TimeoutError(AUTHOR_SECRET)
    app = HttpRoleFixtureLifecycleService(credentials, native, item.journal)
    with pytest.raises(HttpRoleFixtureOutcomeUnknown): app.prepare(item.scope, role_manifest())
    journal = PostgresHttpRoleFixtureJournal(item.pg[1], transaction_guard=item.guard)
    restarted = HttpRoleFixtureLifecycleService(credentials, native, journal)
    with pytest.raises(HttpRoleFixtureOutcomeUnknown): restarted.prepare(item.scope, role_manifest())
    with pytest.raises(HttpRoleFixtureOutcomeUnknown): restarted.cleanup(item.scope, role_manifest())
    assert len(native.calls) == 1 and journal.inspect(item.scope, "setup").result is None


def test_completed_unknown_result_cannot_be_promoted_after_restart(state):
    item = state
    item.journal.claim(item.record, require_current=current)
    unknown = replace(item.record, result=replace(item.result, status="unknown"))
    item.journal.complete(unknown, require_current=current)
    reopened = PostgresHttpRoleFixtureJournal(item.pg[1], transaction_guard=item.guard)
    with pytest.raises(HttpRoleFixtureInvalid):
        reopened.complete(replace(item.record, result=item.result), require_current=current)
    with pytest.raises(HttpRoleFixtureOutcomeUnknown): reopened.claim(item.record, require_current=current)
    assert reopened.inspect(item.scope, "setup") == unknown


def test_current_guard_is_rechecked_after_waiting_for_original_claim_lock(state):
    item = state
    item.journal.claim(item.record, require_current=current)
    entered = Event()
    def guard(session):
        item.guard(session)
        entered.set()
    contender = PostgresHttpRoleFixtureJournal(item.pg[1], transaction_guard=guard)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with item.pg[0].begin() as conn:
            conn.execute(text("SELECT batch_id FROM quality_http_role_fixture_claims WHERE batch_id = :batch FOR UPDATE"),
                         {"batch": item.scope.batch_id})
            future = pool.submit(contender.complete, replace(item.record, result=item.result), require_current=current)
            assert entered.wait(5)
            item.guard.denied = True
        with pytest.raises(HttpRoleFixtureInvalid): future.result(timeout=5)
    item.guard.denied = False
    assert item.journal.inspect(item.scope, "setup") == item.record


@pytest.mark.parametrize("adapter,error", [(PostgresPrivateHttpRoleCredentialEnvelopes, HttpRoleCredentialInvalid),
                                           (PostgresHttpRoleFixtureJournal, HttpRoleFixtureInvalid)])
def test_production_adapters_reject_sqlite_even_before_an_operation(adapter, error):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with pytest.raises(error, match="PostgreSQL"):
            adapter(sessionmaker(bind=engine), transaction_guard=lambda session: None)
    finally:
        engine.dispose()
