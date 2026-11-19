"""PostgreSQL private adapters; no target, public API, or runtime registration.

Every transaction requires a caller-supplied session-aware guard. It must lock
and verify the actual current worker lease/epoch/authority in that same session,
not merely consult a cached approval. The application guards are also checked
inside writes and envelope reads. No secret-bearing events or logs are emitted.
"""
from contextlib import contextmanager
from dataclasses import replace
import base64
import hashlib
import json
import re

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert

from ...application.quality_loop.http_role_credentials import (
    MAX_ROLE_CREDENTIAL_BYTES, HttpRoleCredentialInvalid, HttpRoleFixtureOutcomeUnknown,
    HttpRoleFixturePhaseRecord, HttpRoleResourceBinding, NativeHttpRoleFixtureResult,
)
from ...domain.quality_loop.http_execution_scope import HttpExecutionScope
from ...domain.quality_loop.http_role_fixtures import MAX_ROLE_RESOURCES, HttpRoleFixtureInvalid
from ..runner.execution_vault import SCHEMA as ENVELOPE_SCHEMA
from ..storage.http_role_credentials import MAX_ROLE_CREDENTIAL_ENVELOPE_BYTES
from .database import SessionLocal
from .http_role_fixture_models import (
    HttpRoleCredentialEnvelopeRecord as Envelope, HttpRoleFixtureClaimRecord as Claim,
    HttpRoleFixtureResultRecord as Result,
)


CLAIM_SCHEMA = "nasus.private-http-role-fixture-claim.v1"
RESULT_SCHEMA = "nasus.private-http-role-fixture-result.v1"
MAX_CLAIM_BYTES = 4096
MAX_RESULT_BYTES = 16384
IDENTITY_COLUMNS = ("project_id", "batch_id", "case_id", "phase")


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8", errors="strict")


def _hash(body):
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _matches(value, pattern):
    if type(value) is not str or re.fullmatch(pattern, value) is None:
        raise ValueError()


def _decode(body, limit):
    if type(body) is not bytes or not 1 <= len(body) <= limit:
        raise ValueError()
    value = json.loads(body.decode("utf-8", errors="strict"))
    if _bytes(value) != body:
        raise ValueError()
    return value


def _scope(value):
    if type(value) is not HttpExecutionScope:
        raise ValueError()
    payload = value.payload()
    if len(value.expires_at) > 128:
        raise ValueError()
    return payload


def _key(value):
    _matches(value, r"private-http-role-credentials/[0-9a-f]{64}")
    return value


def _envelope(body):
    value = _decode(body, MAX_ROLE_CREDENTIAL_ENVELOPE_BYTES)
    if type(value) is not dict or set(value) != {"aad", "nonce", "ciphertext"}:
        raise ValueError()
    aad = value["aad"]
    if (type(aad) is not dict or set(aad) != {"schema", "scope", "purpose", "record_id", "key_id"}
            or aad["schema"] != ENVELOPE_SCHEMA or aad["purpose"] != "credential"
            or type(aad["scope"]) is not dict):
        raise ValueError()
    if _scope(HttpExecutionScope(**aad["scope"])) != aad["scope"]:
        raise ValueError()
    _matches(aad["record_id"], r"role-credential:[0-9a-f]{64}")
    _matches(aad["key_id"], r"[A-Za-z0-9_.:-]{1,128}")
    for name in ("nonce", "ciphertext"):
        if type(value[name]) is not str:
            raise ValueError()
        decoded = base64.b64decode(value[name], validate=True)
        if base64.b64encode(decoded).decode("ascii") != value[name]:
            raise ValueError()
        if name == "nonce" and len(decoded) != 12:
            raise ValueError()
        if name == "ciphertext" and not 17 <= len(decoded) <= MAX_ROLE_CREDENTIAL_BYTES + 16:
            raise ValueError()
    return body


def _identity(scope, phase):
    _scope(scope)
    if type(phase) is not str or phase not in {"setup", "cleanup"}:
        raise ValueError()
    return dict(project_id=scope.project_id, batch_id=scope.batch_id, case_id=scope.case_id, phase=phase)


def _claim_bytes(record):
    if type(record) is not HttpRoleFixturePhaseRecord:
        raise ValueError()
    _identity(record.scope, record.phase)
    _matches(record.manifest_hash, r"sha256:[0-9a-f]{64}")
    body = _bytes({"schema": CLAIM_SCHEMA, "scope": _scope(record.scope),
                   "manifest_hash": record.manifest_hash, "phase": record.phase})
    if len(body) > MAX_CLAIM_BYTES:
        raise ValueError()
    return body


def _result_value(result):
    if (type(result) is not NativeHttpRoleFixtureResult or type(result.status) is not str
            or result.status not in {"succeeded", "failed", "unknown"}
            or type(result.resources) is not tuple or len(result.resources) > MAX_ROLE_RESOURCES):
        raise ValueError()
    _matches(result.evidence_digest, r"sha256:[0-9a-f]{64}")
    bindings, resources = set(), []
    for item in result.resources:
        if type(item) is not HttpRoleResourceBinding:
            raise ValueError()
        _matches(item.binding_id, r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}")
        _matches(item.resource_id, r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,255}")
        if item.binding_id in bindings:
            raise ValueError()
        bindings.add(item.binding_id)
        resources.append({"binding_id": item.binding_id, "resource_id": item.resource_id})
    return {"status": result.status, "evidence_digest": result.evidence_digest, "resources": resources}


def _result_bytes(record):
    body = _bytes({"schema": RESULT_SCHEMA, "claim_hash": _hash(_claim_bytes(record)),
                   "result": _result_value(record.result)})
    if len(body) > MAX_RESULT_BYTES:
        raise ValueError()
    return body


def _verify_claim(row):
    value = _decode(row.payload, MAX_CLAIM_BYTES)
    if (type(value) is not dict or set(value) != {"schema", "scope", "manifest_hash", "phase"}
            or value["schema"] != CLAIM_SCHEMA or type(value["scope"]) is not dict):
        raise ValueError()
    record = HttpRoleFixturePhaseRecord(HttpExecutionScope(**value["scope"]), value["manifest_hash"], value["phase"])
    if (_claim_bytes(record) != row.payload or _hash(row.payload) != row.claim_hash
            or any(getattr(row, key) != item for key, item in _identity(record.scope, record.phase).items())):
        raise ValueError()
    return record


def _verify_result(row, record, claim_hash):
    value = _decode(row.payload, MAX_RESULT_BYTES)
    if (type(value) is not dict or set(value) != {"schema", "claim_hash", "result"}
            or value["schema"] != RESULT_SCHEMA or value["claim_hash"] != claim_hash
            or row.claim_hash != claim_hash or _hash(row.payload) != row.content_hash
            or any(getattr(row, key) != item for key, item in _identity(record.scope, record.phase).items())):
        raise ValueError()
    result = value["result"]
    if (type(result) is not dict or set(result) != {"status", "evidence_digest", "resources"}
            or type(result["resources"]) is not list or len(result["resources"]) > MAX_ROLE_RESOURCES):
        raise ValueError()
    resources = []
    for item in result["resources"]:
        if type(item) is not dict or set(item) != {"binding_id", "resource_id"}:
            raise ValueError()
        resources.append(HttpRoleResourceBinding(**item))
    record = replace(record, result=NativeHttpRoleFixtureResult(result["status"], result["evidence_digest"], tuple(resources)))
    if _result_bytes(record) != row.payload:
        raise ValueError()
    return record


class _PostgresPrivateState:
    def __init__(self, session_factory, transaction_guard, error_type):
        self._sessions, self._guard, self._error = session_factory, transaction_guard, error_type
        try:
            if not callable(transaction_guard):
                raise ValueError()
            with session_factory() as session:
                self._require_postgres(session)
        except Exception:
            raise error_type("Private HTTP role persistence requires PostgreSQL and a transaction guard") from None

    @staticmethod
    def _require_postgres(session):
        if session.get_bind().dialect.name != "postgresql":
            raise ValueError()

    def _current(self, session, require_current):
        if not session.in_transaction() or self._guard(session) is not None:
            raise ValueError()
        if require_current is not None and (not callable(require_current) or require_current() is not None):
            raise ValueError()

    @contextmanager
    def _transaction(self, require_current=None):
        try:
            with self._sessions() as session:
                self._require_postgres(session)
                with session.begin():
                    self._current(session, require_current)
                    yield session
                    session.flush()
                    self._current(session, require_current)
        except Exception:
            # Never propagate SQL parameters, driver details, or guard exceptions.
            raise self._error("Private HTTP role state could not be verified or committed") from None


class PostgresPrivateHttpRoleCredentialEnvelopes(_PostgresPrivateState):
    def __init__(self, session_factory=SessionLocal, *, transaction_guard):
        super().__init__(session_factory, transaction_guard, HttpRoleCredentialInvalid)

    def put_if_absent(self, key, envelope, *, require_current):
        with self._transaction(require_current) as session:
            if not callable(require_current):
                raise ValueError()
            _key(key)
            _envelope(envelope)
            inserted = session.scalar(insert(Envelope).values(storage_key=key, envelope=envelope,
                content_hash=_hash(envelope)).on_conflict_do_nothing(index_elements=[Envelope.storage_key])
                .returning(Envelope.storage_key))
        return inserted is not None

    def read(self, key, *, require_current):
        with self._transaction(require_current) as session:
            if not callable(require_current):
                raise ValueError()
            row = session.get(Envelope, _key(key))
            body = None
            if row is not None:
                if row.storage_key != key or row.content_hash != _hash(row.envelope):
                    raise ValueError()
                body = _envelope(row.envelope)
        return body


class PostgresHttpRoleFixtureJournal(_PostgresPrivateState):
    def __init__(self, session_factory=SessionLocal, *, transaction_guard):
        super().__init__(session_factory, transaction_guard, HttpRoleFixtureInvalid)

    def inspect(self, scope, phase):
        with self._transaction() as session:
            identity = _identity(scope, phase)
            # One statement gives a consistent claim/result pair; a still-empty
            # result slot stays unknown and never authorizes a second dispatch.
            pair = session.execute(select(Claim, Result).outerjoin(Result, and_(
                *(getattr(Claim, key) == getattr(Result, key) for key in IDENTITY_COLUMNS)))
                .where(*(getattr(Claim, key) == value for key, value in identity.items()))).one_or_none()
            record = None
            if pair is not None:
                claim, result = pair
                record = _verify_claim(claim)
                if record.scope != scope:
                    raise ValueError()
                if result is not None:
                    record = _verify_result(result, record, claim.claim_hash)
        return record

    def claim(self, record, *, require_current):
        with self._transaction(require_current) as session:
            if not callable(require_current):
                raise ValueError()
            body = _claim_bytes(record)
            if record.result is not None:
                raise ValueError()
            inserted = session.scalar(insert(Claim).values(**_identity(record.scope, record.phase), payload=body,
                claim_hash=_hash(body)).on_conflict_do_nothing(index_elements=list(IDENTITY_COLUMNS))
                .returning(Claim.claim_hash))
        if inserted is None:
            raise HttpRoleFixtureOutcomeUnknown("Original role fixture phase is already claimed; never resend")

    def complete(self, record, *, require_current):
        with self._transaction(require_current) as session:
            if not callable(require_current):
                raise ValueError()
            body = _result_bytes(record)
            identity = _identity(record.scope, record.phase)
            row = session.scalar(select(Claim).filter_by(**identity).with_for_update())
            # Recheck after a potentially blocking row lock, not just at entry.
            self._current(session, require_current)
            if row is None or _verify_claim(row) != replace(record, result=None):
                raise ValueError()
            if session.get(Result, tuple(identity[key] for key in IDENTITY_COLUMNS)) is not None:
                raise ValueError()
            session.add(Result(**identity, claim_hash=row.claim_hash, payload=body, content_hash=_hash(body)))
