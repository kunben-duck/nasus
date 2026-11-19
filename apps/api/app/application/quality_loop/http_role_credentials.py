"""Private role credentials and native fixture ports; no runtime registration.

Integrators must supply a current lease/confirmed-tool authority, private storage,
an allowlisted native adapter, and a durable single-assignment dispatch journal.
Neither a manifest, a scope, nor a credential reference grants authority.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import re
from typing import Callable, Protocol

from ...domain.quality_loop.http_execution_scope import HttpExecutionScope
from ...domain.quality_loop.http_role_fixtures import (
    HTTP_FIXTURE_ROLES, MAX_ROLE_RESOURCES, HttpRoleFixtureInvalid, http_role_fixture_manifest_digest,
    validate_http_role_fixture_manifest,
)


MAX_ROLE_CREDENTIAL_BYTES = 16 * 1024
PRIVATE_ROLE_CREDENTIAL_SCHEMA = "nasus.private-http-role-credential.v1"


class HttpRoleCredentialInvalid(ValueError):
    pass


class HttpRoleCredentialAccessDenied(PermissionError):
    pass


class HttpRoleFixtureOutcomeUnknown(RuntimeError):
    pass


def _now():
    return datetime.now(timezone.utc)


def _fresh(scope, clock):
    try:
        if type(scope) is not HttpExecutionScope:
            raise ValueError()
        scope.payload()
        now = clock()
        if not isinstance(now, datetime) or now.tzinfo is None or scope.deadline() <= now:
            raise ValueError()
    except Exception:
        raise HttpRoleCredentialAccessDenied("Private role scope is invalid or expired") from None


@dataclass(frozen=True, repr=False)
class HttpRoleCredential:
    """Secret-bearing native value. Never serialize this into public evidence."""
    kind: str
    token: str | None = field(default=None, repr=False)
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)

    def __repr__(self):
        return "HttpRoleCredential(<redacted>)"

    def __post_init__(self):
        try:
            if self.kind in ("bearer", "token"):
                values = ((self.token, 8192),)
                valid = self.username is None and self.password is None
            elif self.kind == "basic":
                values = ((self.username, 512), (self.password, 2048))
                valid = self.token is None and type(self.username) is str and ":" not in self.username
            else:
                raise ValueError()
            if type(self.kind) is not str or not valid:
                raise ValueError()
            for value, limit in values:
                if (type(value) is not str or not 1 <= len(value.encode("utf-8", errors="strict")) <= limit
                        or not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                    raise ValueError()
        except Exception:
            raise HttpRoleCredentialInvalid("Private role credential is invalid") from None

    def private_bytes(self):
        return json.dumps({"schema": PRIVATE_ROLE_CREDENTIAL_SCHEMA, "kind": self.kind,
                           "token": self.token, "username": self.username, "password": self.password},
                          sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")

    @classmethod
    def from_private_bytes(cls, body):
        try:
            if type(body) is not bytes or not 1 <= len(body) <= MAX_ROLE_CREDENTIAL_BYTES:
                raise ValueError()
            value = json.loads(body.decode("utf-8", errors="strict"))
            if (type(value) is not dict or set(value) != {"schema", "kind", "token", "username", "password"}
                    or value.pop("schema") != PRIVATE_ROLE_CREDENTIAL_SCHEMA):
                raise ValueError()
            result = cls(**value)
            # Exact canonical readback also rejects duplicate JSON keys.
            if result.private_bytes() != body:
                raise ValueError()
            return result
        except Exception:
            raise HttpRoleCredentialInvalid("Private role credential cannot be decoded") from None


@dataclass(frozen=True)
class ResolvedHttpRoleAuth:
    role: str
    credential: HttpRoleCredential | None = field(repr=False)

    def __post_init__(self):
        if (type(self.role) is not str or self.role not in HTTP_FIXTURE_ROLES
                or (self.role == "anonymous" and self.credential is not None)
                or (self.role != "anonymous" and type(self.credential) is not HttpRoleCredential)):
            raise HttpRoleCredentialInvalid("Role authentication must be explicit and isolated")


class HttpRoleCredentialAuthorityPort(Protocol):
    def require_current(self, scope: HttpExecutionScope, *, manifest_hash: str, role: str | None,
                        credential_ref: str | None, operation: str) -> None:
        """Recheck live batch lease, epoch, source ACL and separately confirmed tool.

        Bind the *exact* scope/manifest/role/ref and operation, not possession of
        these inputs. Operations are store_credential, resolve_credential,
        fixture_setup and fixture_cleanup. No cached approval or implicit tool
        confirmation is sufficient. The implementation must capture and fence
        the actual worker lease token and confirmed invocation, not merely check
        that some lease is active. This port must raise when authority is lost.
        """
        ...


class HttpRoleCredentialStoragePort(Protocol):
    def put(self, scope, *, manifest_hash, role, credential_ref, credential,
            require_current: Callable[[], None]) -> None: ...

    def get(self, scope, *, manifest_hash, role, credential_ref,
            require_current: Callable[[], None]) -> HttpRoleCredential: ...


class HttpRoleCredentialService:
    def __init__(self, storage: HttpRoleCredentialStoragePort, authority: HttpRoleCredentialAuthorityPort,
                 *, clock: Callable[[], datetime] = _now):
        self._storage, self._authority, self._clock = storage, authority, clock

    def _context(self, scope, value, role=None):
        _fresh(scope, self._clock)
        manifest = validate_http_role_fixture_manifest(value)
        if manifest["case_id"] != scope.case_id:
            raise HttpRoleFixtureInvalid("Role fixture differs from the fixed case scope")
        if role is not None and (type(role) is not str or role not in HTTP_FIXTURE_ROLES):
            raise HttpRoleCredentialInvalid("Role must be explicitly declared")
        reference = manifest["roles"][role]["credential_ref"] if role is not None else None
        return manifest, http_role_fixture_manifest_digest(manifest), reference

    def current_guard(self, scope, value, *, role=None, operation):
        _, digest, reference = self._context(scope, value, role)
        if operation not in ("store_credential", "resolve_credential", "fixture_setup", "fixture_cleanup"):
            raise HttpRoleCredentialAccessDenied("Private role operation is not supported")

        def current():
            _fresh(scope, self._clock)
            try:
                checked = self._authority.require_current(scope, manifest_hash=digest, role=role,
                                                           credential_ref=reference, operation=operation)
                if checked is not None:
                    raise ValueError()
            except Exception:
                raise HttpRoleCredentialAccessDenied("Current private role authority is required") from None
            _fresh(scope, self._clock)
        return current

    def store(self, scope: HttpExecutionScope, value, role: str, credential: HttpRoleCredential) -> None:
        if type(role) is not str or role not in HTTP_FIXTURE_ROLES:
            raise HttpRoleCredentialInvalid("Role must be explicitly declared")
        manifest, digest, reference = self._context(scope, value, role)
        if role == "anonymous" or type(credential) is not HttpRoleCredential:
            raise HttpRoleCredentialInvalid("Anonymous cannot hold or inherit a credential")
        current = self.current_guard(scope, manifest, role=role, operation="store_credential")
        current()
        try:
            self._storage.put(scope, manifest_hash=digest, role=role, credential_ref=reference,
                              credential=credential, require_current=current)
        except Exception:
            raise HttpRoleCredentialInvalid("Private role credential cannot be stored") from None
        current()

    def resolve(self, scope: HttpExecutionScope, value, role: str) -> ResolvedHttpRoleAuth:
        if type(role) is not str or role not in HTTP_FIXTURE_ROLES:
            raise HttpRoleCredentialInvalid("Role must be explicitly declared")
        manifest, digest, reference = self._context(scope, value, role)
        current = self.current_guard(scope, manifest, role=role, operation="resolve_credential")
        current()
        if role == "anonymous":
            return ResolvedHttpRoleAuth(role, None)
        try:
            credential = self._storage.get(scope, manifest_hash=digest, role=role, credential_ref=reference,
                                           require_current=current)
            result = ResolvedHttpRoleAuth(role, credential)
        except Exception:
            raise HttpRoleCredentialInvalid("Private role credential cannot be resolved") from None
        current()
        return result


@dataclass(frozen=True)
class HttpRoleResourceBinding:
    binding_id: str
    resource_id: str = field(repr=False)


@dataclass(frozen=True)
class NativeHttpRoleFixtureResult:
    """Native receipt summary, never credentials, headers, or business coverage."""
    status: str
    evidence_digest: str
    resources: tuple[HttpRoleResourceBinding, ...] = field(default=(), repr=False)


class NativeHttpRoleFixtureAdapterPort(Protocol):
    def validate_recipes(self, manifest: dict) -> None:
        """Pure allowlist check for native recipe IDs; no SQL, shell, URL or I/O."""
        ...

    def setup(self, scope, manifest, *, credentials: HttpRoleCredentialService,
              require_current: Callable[[], None]) -> NativeHttpRoleFixtureResult:
        """Run only declared steps after independently confirmed fixture_setup.

        Recheck current at each native side-effect boundary. Persist generated
        role credentials privately through credentials.store, never in receipts.
        Provision distinct isolated principals for the two authenticated roles.
        Resolve each explicit role separately; anonymous must use a clean no-auth
        client without inherited cookies/headers. No business-test execution.
        Unknown writes must stop without native transport retries.
        """
        ...

    def cleanup(self, scope, manifest, prepared: NativeHttpRoleFixtureResult, *,
                credentials: HttpRoleCredentialService,
                require_current: Callable[[], None]) -> NativeHttpRoleFixtureResult:
        """Only exact original resources/roles; same fencing/no-retry rules as setup.

        Missing resources from a failed setup are unresolved, never guessed.
        evidence_digest must identify original native proof, not a fabricated
        success. Cleanup does not prove baseline restoration or business coverage.
        """
        ...


@dataclass(frozen=True)
class HttpRoleFixturePhaseRecord:
    scope: HttpExecutionScope
    manifest_hash: str
    phase: str
    result: NativeHttpRoleFixtureResult | None = None


class HttpRoleFixtureJournalPort(Protocol):
    def inspect(self, scope, phase) -> HttpRoleFixturePhaseRecord | None: ...

    def claim(self, record: HttpRoleFixturePhaseRecord, *, require_current: Callable[[], None]) -> None:
        """Atomically reserve unique (project,batch,case,phase), not manifest hash.

        Never replace a claim or evade it via version/env/epoch/expiry changes.
        Check current inside the transaction. A missing result is unknown, not
        permission to resend. Durable claims are required before native writes.
        """
        ...

    def complete(self, record: HttpRoleFixturePhaseRecord, *, require_current: Callable[[], None]) -> None:
        """Single assignment against the exact reserved scope/hash; no overwrite."""
        ...


class HttpRoleFixtureLifecycleService:
    def __init__(self, credentials: HttpRoleCredentialService, adapter: NativeHttpRoleFixtureAdapterPort,
                 journal: HttpRoleFixtureJournalPort):
        self._credentials, self._adapter, self._journal = credentials, adapter, journal

    @staticmethod
    def _result(manifest, result, prepared=None):
        try:
            if (type(result) is not NativeHttpRoleFixtureResult or type(result.status) is not str
                    or result.status not in {"succeeded", "failed", "unknown"}
                    or type(result.evidence_digest) is not str
                    or re.fullmatch(r"sha256:[0-9a-f]{64}", result.evidence_digest) is None
                    or type(result.resources) is not tuple or len(result.resources) > MAX_ROLE_RESOURCES):
                raise ValueError()
            bindings = {}
            for item in result.resources:
                if (type(item) is not HttpRoleResourceBinding or type(item.binding_id) is not str
                        or item.binding_id not in manifest["resource_bindings"] or item.binding_id in bindings
                        or type(item.resource_id) is not str
                        or re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,255}", item.resource_id) is None):
                    raise ValueError()
                bindings[item.binding_id] = item.resource_id
            expected = ({item.binding_id: item.resource_id for item in prepared.resources}
                        if prepared is not None else None)
            if expected is not None and any(expected.get(key) != value for key, value in bindings.items()):
                raise ValueError()
            if result.status == "succeeded" and set(bindings) != set(
                    expected if expected is not None else manifest["resource_bindings"]):
                raise ValueError()
            return result
        except Exception:
            raise HttpRoleFixtureInvalid("Native role fixture receipt is invalid") from None

    def _phase(self, scope, value, phase, *, dispatch, prepared=None):
        manifest, digest, _ = self._credentials._context(scope, value)
        operation = "fixture_cleanup" if not dispatch else "fixture_" + phase
        current = self._credentials.current_guard(scope, manifest, operation=operation)
        current()
        try:
            prior = self._journal.inspect(scope, phase)
        except Exception:
            raise HttpRoleFixtureOutcomeUnknown("Original fixture dispatch cannot be read; never resend") from None
        current()
        if prior is not None:
            if (type(prior) is not HttpRoleFixturePhaseRecord or prior.scope != scope
                    or prior.manifest_hash != digest or prior.phase != phase):
                raise HttpRoleFixtureInvalid("Original role fixture dispatch cannot be rebound")
            if prior.result is None:
                raise HttpRoleFixtureOutcomeUnknown("Original fixture write is unknown; never resend")
            result = self._result(manifest, prior.result, prepared)
            if result.status == "unknown":
                raise HttpRoleFixtureOutcomeUnknown("Original fixture write is unknown; never resend")
            return result
        if not dispatch:
            raise HttpRoleFixtureOutcomeUnknown("Original fixture setup is unavailable; never resend")
        try:
            if self._adapter.validate_recipes(deepcopy(manifest)) is not None:
                raise ValueError()
        except Exception:
            raise HttpRoleFixtureInvalid("Native fixture recipe is not supported") from None
        current()
        try:
            self._journal.claim(HttpRoleFixturePhaseRecord(scope, digest, phase), require_current=current)
            current()
            if phase == "setup":
                result = self._adapter.setup(scope, deepcopy(manifest), credentials=self._credentials,
                                             require_current=current)
            else:
                result = self._adapter.cleanup(scope, deepcopy(manifest), prepared, credentials=self._credentials,
                                               require_current=current)
            current()
            result = self._result(manifest, result, prepared)
            self._journal.complete(HttpRoleFixturePhaseRecord(scope, digest, phase, result), require_current=current)
            current()
        except Exception:
            raise HttpRoleFixtureOutcomeUnknown("Fixture write lacks a confirmed original result; never resend") from None
        if result.status == "unknown":
            raise HttpRoleFixtureOutcomeUnknown("Original fixture write is unknown; never resend")
        return result

    def prepare(self, scope: HttpExecutionScope, value):
        return self._phase(scope, value, "setup", dispatch=True)

    def cleanup(self, scope: HttpExecutionScope, value):
        prepared = self._phase(scope, value, "setup", dispatch=False)
        return self._phase(scope, value, "cleanup", dispatch=True, prepared=prepared)
