"""Real encryption with local protocol doubles, never target/DB execution."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from threading import Lock
import traceback

import pytest

from apps.api.app.application.quality_loop.http_role_credentials import (
    HttpRoleCredential, HttpRoleCredentialAccessDenied, HttpRoleCredentialInvalid,
    HttpRoleCredentialService, ResolvedHttpRoleAuth,
)
from apps.api.app.domain.quality_loop.http_execution_scope import HttpExecutionScope
from apps.api.app.domain.quality_loop.http_role_fixtures import HttpRoleFixtureInvalid, http_role_fixture_manifest_digest
from apps.api.app.infrastructure.runner.execution_vault import ExecutionEnvelopeCipher
from apps.api.app.infrastructure.storage.http_role_credentials import EncryptedHttpRoleCredentialStore
from apps.api.tests.test_http_role_fixtures_v2 import role_manifest


NOW = datetime(2026, 11, 18, tzinfo=timezone.utc)
SCOPE = HttpExecutionScope("project", "version", "batch", "case", "environment", 1,
                           "sha256:" + "a" * 64, (NOW + timedelta(minutes=10)).isoformat())
AUTHOR_SECRET = "private-author-token-never-public"
OTHER_SECRET = "private-other-password-never-public"


class MemoryEnvelopes:
    """Private backend double, not production storage or a durable journal."""
    def __init__(self):
        self.values, self.lock = {}, Lock()
        self.reads = self.writes = 0
        self.after_read = lambda: None
        self.after_write = lambda: None

    def put_if_absent(self, key, envelope, *, require_current):
        with self.lock:
            require_current()
            self.writes += 1
            if key in self.values:
                return False
            assert type(envelope) is bytes and key.startswith("private-http-role-credentials/")
            self.values[key] = envelope
            self.after_write()
            return True

    def read(self, key, *, require_current):
        require_current()
        self.reads += 1
        value = self.values.get(key)
        self.after_read()
        return value


class Authority:
    def __init__(self):
        self.allowed = True
        self.calls = []
        self.scope = SCOPE
        self.manifest = role_manifest()
        self.confirmed = {"store_credential", "resolve_credential", "fixture_setup", "fixture_cleanup"}

    def require_current(self, scope, *, manifest_hash, role, credential_ref, operation):
        self.calls.append((scope, manifest_hash, role, credential_ref, operation))
        expected_ref = self.manifest["roles"][role]["credential_ref"] if role else None
        if (not self.allowed or scope != self.scope or operation not in self.confirmed
                or manifest_hash != http_role_fixture_manifest_digest(self.manifest) or credential_ref != expected_ref):
            raise PermissionError(AUTHOR_SECRET)


def credential_service():
    backend, authority, clock = MemoryEnvelopes(), Authority(), [NOW]
    store = EncryptedHttpRoleCredentialStore(ExecutionEnvelopeCipher(b"a" * 32, "key-1"), backend,
                                              clock=lambda: clock[0])
    service = HttpRoleCredentialService(store, authority, clock=lambda: clock[0])
    return service, store, backend, authority, clock


def store_author(service):
    service.store(SCOPE, role_manifest(), "author", HttpRoleCredential("token", token=AUTHOR_SECRET))


def assert_redacted(error):
    formatted = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    assert AUTHOR_SECRET not in str(error) + repr(error) + formatted
    assert OTHER_SECRET not in str(error) + repr(error) + formatted
    assert error.__cause__ is None


def test_encrypted_write_readback_separate_roles_anonymous_no_auth_and_safe_repr(caplog):
    service, _, backend, authority, _ = credential_service()
    store_author(service)
    service.store(SCOPE, role_manifest(), "other", HttpRoleCredential("basic", username="private-user", password=OTHER_SECRET))
    author = service.resolve(SCOPE, role_manifest(), "author")
    other = service.resolve(SCOPE, role_manifest(), "other")
    reads = backend.reads
    anonymous = service.resolve(SCOPE, role_manifest(), "anonymous")
    assert author.credential.token == AUTHOR_SECRET
    assert other.credential.password == OTHER_SECRET and other.credential.token is None
    assert anonymous == ResolvedHttpRoleAuth("anonymous", None) and backend.reads == reads
    assert len(backend.values) == 2
    public = repr([author, other, anonymous, author.credential, other.credential]) + repr(authority.calls) + caplog.text
    stored = b"".join(backend.values.values()).decode()
    for secret in (AUTHOR_SECRET, OTHER_SECRET, "private-user"):
        assert secret not in public + stored
    for encoded in backend.values.values():
        envelope = json.loads(encoded)
        assert envelope["aad"]["purpose"] == "credential"
        assert envelope["aad"]["scope"] == SCOPE.payload()


def test_real_cipher_reopen_from_new_service_and_fresh_nonce():
    first, _, backend, authority, clock = credential_service()
    store_author(first)
    reopened = HttpRoleCredentialService(
        EncryptedHttpRoleCredentialStore(ExecutionEnvelopeCipher(b"a" * 32, "key-1"), backend, clock=lambda: clock[0]),
        authority, clock=lambda: clock[0])
    assert reopened.resolve(SCOPE, role_manifest(), "author").credential.token == AUTHOR_SECRET
    second, _, second_backend, _, _ = credential_service()
    store_author(second)
    assert next(iter(backend.values.values())) != next(iter(second_backend.values.values()))


def test_write_once_reference_cannot_replace_or_extend_existing_credentials():
    service, store, backend, _, _ = credential_service()
    store_author(service)
    original = deepcopy(backend.values)
    for scope in (SCOPE, replace(SCOPE, expires_at=(NOW + timedelta(hours=1)).isoformat()),
                  replace(SCOPE, environment_epoch=2)):
        with pytest.raises(HttpRoleCredentialInvalid):
            store.put(scope, manifest_hash=http_role_fixture_manifest_digest(role_manifest()), role="author",
                      credential_ref=role_manifest()["roles"]["author"]["credential_ref"],
                      credential=HttpRoleCredential("bearer", token="replacement"), require_current=lambda: None)
    assert backend.values == original
    assert service.resolve(SCOPE, role_manifest(), "author").credential.token == AUTHOR_SECRET


@pytest.mark.parametrize("field,value", [
    ("project_id", "other"), ("version_id", "other"), ("batch_id", "other"), ("case_id", "other"),
    ("environment_id", "other"), ("environment_epoch", 2), ("inventory_hash", "sha256:" + "b" * 64),
    ("expires_at", (NOW + timedelta(hours=1)).isoformat()),
])
def test_cipher_rejects_cross_scope_replay_even_if_backend_returns_foreign_envelope(field, value):
    service, store, backend, _, _ = credential_service()
    store_author(service)
    encrypted = next(iter(backend.values.values()))
    backend.read = lambda *args, **kwargs: encrypted
    with pytest.raises(HttpRoleCredentialInvalid) as caught:
        store.get(replace(SCOPE, **{field: value}), manifest_hash=http_role_fixture_manifest_digest(role_manifest()),
                  role="author", credential_ref=role_manifest()["roles"]["author"]["credential_ref"],
                  require_current=lambda: None)
    assert_redacted(caught.value)


@pytest.mark.parametrize("change", ["role", "reference", "manifest", "ciphertext", "nonce", "aad", "key", "key_id",
                                    "duplicate", "noncanonical", "oversized", "malformed", "missing"])
def test_tampered_or_rebound_envelopes_do_not_resolve(change):
    service, store, backend, _, clock = credential_service()
    store_author(service)
    key, encoded = next(iter(backend.values.items()))
    context = dict(manifest_hash=http_role_fixture_manifest_digest(role_manifest()), role="author",
                   credential_ref=role_manifest()["roles"]["author"]["credential_ref"])
    if change == "role": context["role"] = "other"
    if change == "reference": context["credential_ref"] = "credential:" + "3" * 32
    if change == "manifest": context["manifest_hash"] = "sha256:" + "f" * 64
    if change in {"role", "reference", "manifest"}:
        backend.read = lambda *args, **kwargs: encoded
    if change in {"ciphertext", "nonce", "aad"}:
        envelope = json.loads(encoded)
        if change == "aad": envelope["aad"]["scope"]["environment_epoch"] = 2
        else: envelope[change] = ("A" if envelope[change][0] != "A" else "B") + envelope[change][1:]
        backend.values[key] = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    if change in {"key", "key_id"}:
        store = EncryptedHttpRoleCredentialStore(
            ExecutionEnvelopeCipher((b"b" if change == "key" else b"a") * 32, "key-2" if change == "key_id" else "key-1"),
            backend, clock=lambda: clock[0])
    if change == "duplicate": backend.values[key] = encoded.replace(b'"aad":', b'"aad":{},"aad":', 1)
    if change == "noncanonical": backend.values[key] = encoded + b"\n"
    if change == "oversized": backend.values[key] = b"x" * (32 * 1024 + 1)
    if change == "malformed": backend.values[key] = AUTHOR_SECRET.encode()
    if change == "missing": backend.values.clear()
    with pytest.raises(HttpRoleCredentialInvalid) as caught:
        store.get(SCOPE, **context, require_current=lambda: None)
    assert_redacted(caught.value)


@pytest.mark.parametrize("when", ["before_read", "during_read", "before_write", "during_write", "unconfirmed"])
def test_authority_denial_or_revocation_never_returns_secrets(when):
    service, _, backend, authority, _ = credential_service()
    if "read" in when or when == "unconfirmed": store_author(service)
    def revoke():
        authority.allowed = False
    if when.startswith("before"): revoke()
    if when == "during_read": backend.after_read = revoke
    if when == "during_write": backend.after_write = revoke
    if when == "unconfirmed": authority.confirmed.remove("resolve_credential")
    with pytest.raises((HttpRoleCredentialAccessDenied, HttpRoleCredentialInvalid)) as caught:
        if "write" in when: store_author(service)
        else: service.resolve(SCOPE, role_manifest(), "author")
    assert_redacted(caught.value)
    if when == "before_read": assert backend.reads == 0
    if when == "before_write": assert backend.writes == 0


@pytest.mark.parametrize("offset", [timedelta(minutes=10), timedelta(days=1)])
def test_expiry_is_enforced_for_reads_writes_and_anonymous(offset):
    service, _, backend, _, clock = credential_service()
    store_author(service)
    clock[0] = NOW + offset
    for role in ("author", "anonymous"):
        with pytest.raises(HttpRoleCredentialAccessDenied): service.resolve(SCOPE, role_manifest(), role)
    with pytest.raises(HttpRoleCredentialAccessDenied): store_author(service)
    assert backend.reads == 0 and backend.writes == 1


def test_expiration_during_read_and_naive_clock_fail_closed():
    service, _, backend, _, clock = credential_service()
    store_author(service)
    backend.after_read = lambda: clock.__setitem__(0, NOW + timedelta(minutes=10))
    with pytest.raises(HttpRoleCredentialInvalid): service.resolve(SCOPE, role_manifest(), "author")
    clock[0] = NOW.replace(tzinfo=None)
    with pytest.raises(HttpRoleCredentialAccessDenied): service.resolve(SCOPE, role_manifest(), "anonymous")


def test_anonymous_and_unknown_roles_cannot_store_or_inherit_credentials():
    service, _, backend, authority, _ = credential_service()
    credential = HttpRoleCredential("token", token=AUTHOR_SECRET)
    for role in ("anonymous", "fallback", None, True, {}):
        with pytest.raises(HttpRoleCredentialInvalid): service.store(SCOPE, role_manifest(), role, credential)
    with pytest.raises(HttpRoleCredentialInvalid): ResolvedHttpRoleAuth("anonymous", credential)
    with pytest.raises(HttpRoleCredentialInvalid): ResolvedHttpRoleAuth("author", None)
    assert backend.reads == backend.writes == 0
    authority.allowed = False
    with pytest.raises(HttpRoleCredentialAccessDenied): service.resolve(SCOPE, role_manifest(), "anonymous")
    manifest = role_manifest()
    manifest["roles"]["anonymous"]["credential_ref"] = manifest["roles"]["author"]["credential_ref"]
    with pytest.raises(HttpRoleFixtureInvalid): service.resolve(SCOPE, manifest, "anonymous")


@pytest.mark.parametrize("kwargs", [
    {"kind": "cookie", "token": AUTHOR_SECRET}, {"kind": "bearer", "token": ""},
    {"kind": "bearer", "token": "secret\r\nInjected: yes"}, {"kind": "token", "token": "x" * 8193},
    {"kind": "basic", "username": "private", "password": "x" * 2049},
    {"kind": "basic", "username": "private:other", "password": OTHER_SECRET},
    {"kind": "basic", "username": "private", "password": OTHER_SECRET, "token": AUTHOR_SECRET},
    {"kind": "token", "token": AUTHOR_SECRET, "username": "private"},
    {"kind": "token", "token": "\ud800"}, {"kind": [], "token": AUTHOR_SECRET},
])
def test_invalid_secret_material_has_constant_redacted_errors(kwargs):
    with pytest.raises(HttpRoleCredentialInvalid) as caught: HttpRoleCredential(**kwargs)
    assert_redacted(caught.value)


def test_private_payload_readback_is_bounded_canonical_and_closed():
    credential = HttpRoleCredential("bearer", token=AUTHOR_SECRET)
    body = credential.private_bytes()
    assert HttpRoleCredential.from_private_bytes(body) == credential
    for invalid in (body + b"\n", body.replace(b'"token":', b'"token":"other","token":'),
                    body.replace(b'"kind":', b'"headers":{},"kind":'), b"{}", b"x" * (16 * 1024 + 1)):
        with pytest.raises(HttpRoleCredentialInvalid) as caught: HttpRoleCredential.from_private_bytes(invalid)
        assert_redacted(caught.value)


@pytest.mark.parametrize("response", [False, True, {"token": AUTHOR_SECRET}])
def test_malformed_authority_port_response_is_not_implicit_permission(response):
    service, _, backend, authority, _ = credential_service()
    authority.require_current = lambda *args, **kwargs: response
    with pytest.raises(HttpRoleCredentialAccessDenied) as caught:
        service.resolve(SCOPE, role_manifest(), "anonymous")
    assert_redacted(caught.value)
    assert backend.reads == backend.writes == 0


def test_cipher_enforces_expiry_even_when_called_below_service_boundary():
    service, store, _, _, clock = credential_service()
    store_author(service)
    clock[0] = NOW + timedelta(minutes=10)
    context = dict(manifest_hash=http_role_fixture_manifest_digest(role_manifest()), role="author",
                   credential_ref=role_manifest()["roles"]["author"]["credential_ref"], require_current=lambda: None)
    with pytest.raises(HttpRoleCredentialInvalid): store.get(SCOPE, **context)
    with pytest.raises(HttpRoleCredentialInvalid):
        store.put(SCOPE, **context, credential=HttpRoleCredential("token", token=AUTHOR_SECRET))


def test_authenticated_but_invalid_private_payload_is_not_returned():
    service, store, backend, _, _ = credential_service()
    store_author(service)
    key, encoded = next(iter(backend.values.items()))
    aad = json.loads(encoded)["aad"]
    invalid = json.dumps({"token": AUTHOR_SECRET, "headers": {"Authorization": AUTHOR_SECRET}}).encode()
    envelope = ExecutionEnvelopeCipher(b"a" * 32, "key-1").seal(
        invalid, scope=SCOPE, purpose="credential", record_id=aad["record_id"], now=NOW)
    backend.values[key] = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(HttpRoleCredentialInvalid) as caught:
        service.resolve(SCOPE, role_manifest(), "author")
    assert_redacted(caught.value)
