"""Encrypted private credential storage, deliberately outside public artifacts.

The injected envelope backend must be private, durable and write-once. No backend,
key management, native target, or application container is registered here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Callable, Protocol

from ...application.quality_loop.http_role_credentials import HttpRoleCredential, HttpRoleCredentialInvalid
from ...domain.quality_loop.http_execution_scope import HttpExecutionScope
from ...domain.quality_loop.http_role_fixtures import validate_role_credential_reference
from ..runner.execution_vault import ExecutionEnvelopeCipher


MAX_ROLE_CREDENTIAL_ENVELOPE_BYTES = 32 * 1024


class PrivateHttpRoleCredentialEnvelopePort(Protocol):
    def put_if_absent(self, key: str, envelope: bytes, *, require_current: Callable[[], None]) -> bool:
        """Atomically recheck current and persist ciphertext only; false if occupied.

        Never overwrite, publish, or log envelopes. No key or plaintext payload
        belongs in the backend's object metadata or public artifact namespace.
        """
        ...

    def read(self, key: str, *, require_current: Callable[[], None]) -> bytes | None:
        """Recheck current at the private read boundary; None means unavailable."""
        ...


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8", errors="strict")


def _coordinates(scope, manifest_hash, role, credential_ref):
    if (type(scope) is not HttpExecutionScope or type(manifest_hash) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", manifest_hash) is None
            or type(role) is not str or role not in {"author", "other"}):
        raise ValueError()
    scope.payload()
    validate_role_credential_reference(credential_ref)
    # Key uniqueness deliberately excludes epoch/expiry: extending a lifetime
    # cannot overwrite an existing reference. AAD still binds the complete scope.
    key_identity = {"project_id": scope.project_id, "batch_id": scope.batch_id,
                    "case_id": scope.case_id, "role": role, "credential_ref": credential_ref}
    key = "private-http-role-credentials/" + hashlib.sha256(_bytes(key_identity)).hexdigest()
    record = {"manifest_hash": manifest_hash, "role": role, "credential_ref": credential_ref}
    record_id = "role-credential:" + hashlib.sha256(_bytes(record)).hexdigest()
    return key, record_id


class EncryptedHttpRoleCredentialStore:
    def __init__(self, cipher: ExecutionEnvelopeCipher, envelopes: PrivateHttpRoleCredentialEnvelopePort,
                 *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._cipher, self._envelopes, self._clock = cipher, envelopes, clock

    def put(self, scope, *, manifest_hash, role, credential_ref, credential, require_current):
        try:
            require_current()
            key, record_id = _coordinates(scope, manifest_hash, role, credential_ref)
            if type(credential) is not HttpRoleCredential:
                raise ValueError()
            body = credential.private_bytes()
            # Enforce the same bounded canonical payload on write and read.
            HttpRoleCredential.from_private_bytes(body)
            envelope = self._cipher.seal(body, scope=scope, purpose="credential", record_id=record_id,
                                         now=self._clock())
            encoded = _bytes(envelope)
            if len(encoded) > MAX_ROLE_CREDENTIAL_ENVELOPE_BYTES:
                raise ValueError()
            require_current()
            if self._envelopes.put_if_absent(key, encoded, require_current=require_current) is not True:
                raise ValueError()
            require_current()
        except Exception:
            raise HttpRoleCredentialInvalid("Private role credential cannot be stored") from None

    def get(self, scope, *, manifest_hash, role, credential_ref, require_current):
        try:
            require_current()
            key, record_id = _coordinates(scope, manifest_hash, role, credential_ref)
            encoded = self._envelopes.read(key, require_current=require_current)
            require_current()
            if type(encoded) is not bytes or not 1 <= len(encoded) <= MAX_ROLE_CREDENTIAL_ENVELOPE_BYTES:
                raise ValueError()
            envelope = json.loads(encoded.decode("utf-8", errors="strict"))
            if _bytes(envelope) != encoded:
                raise ValueError()
            body = self._cipher.open(envelope, scope=scope, purpose="credential", record_id=record_id,
                                     now=self._clock())
            credential = HttpRoleCredential.from_private_bytes(body)
            require_current()
            return credential
        except Exception:
            raise HttpRoleCredentialInvalid("Private role credential cannot be resolved") from None
