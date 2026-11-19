"""Authenticated private envelopes, separate from public runner evidence.

The caller must recheck the current batch lease and source ACL before opening.
This codec neither stores keys in artifacts nor grants execution authority.
"""
import base64
import binascii
from datetime import datetime, timezone
import json
import os
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ...domain.quality_loop.http_execution_scope import HttpExecutionScope
from ...domain.quality_loop.execution_environment_lifecycle import BatchSnapshotScope, SNAPSHOT_SCHEMA


SCHEMA = "nasus.private-http-envelope.v1"
MAX_PRIVATE_BYTES = 16 * 1024 * 1024


class PrivateExecutionEnvelopeInvalid(ValueError):
    pass


def _aad(scope, purpose, record_id, key_id):
    snapshot = isinstance(scope, BatchSnapshotScope) and purpose == "snapshot"
    if not snapshot and (not isinstance(scope, HttpExecutionScope) or purpose not in {"credential", "evidence"}):
        raise PrivateExecutionEnvelopeInvalid("Private HTTP envelope purpose or scope is invalid")
    if any(type(value) is not str or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value)
           for value in (record_id, key_id)):
        raise PrivateExecutionEnvelopeInvalid("Private HTTP envelope identity is invalid")
    return {"schema": SNAPSHOT_SCHEMA if snapshot else SCHEMA, "scope": scope.payload(),
            "purpose": purpose, "record_id": record_id, "key_id": key_id}


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class ExecutionEnvelopeCipher:
    def __init__(self, key: bytes, key_id: str):
        if type(key) is not bytes or len(key) != 32:
            raise PrivateExecutionEnvelopeInvalid("Private HTTP envelope requires a 256-bit key")
        self._cipher, self._key_id = AESGCM(key), key_id

    @staticmethod
    def _fresh(scope, purpose, now):
        if purpose == "credential":
            if not isinstance(now, datetime) or now.tzinfo is None or scope.deadline() <= now:
                raise PrivateExecutionEnvelopeInvalid("Private HTTP credential has expired")

    def seal(self, body, *, scope, purpose, record_id, now=None):
        aad = _aad(scope, purpose, record_id, self._key_id)
        self._fresh(scope, purpose, now or datetime.now(timezone.utc))
        if type(body) is not bytes or not 1 <= len(body) <= MAX_PRIVATE_BYTES:
            raise PrivateExecutionEnvelopeInvalid("Private HTTP payload exceeds its byte bound")
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(nonce, body, _bytes(aad))
        return {"aad": aad, "nonce": base64.b64encode(nonce).decode(),
                "ciphertext": base64.b64encode(ciphertext).decode()}

    def open(self, envelope, *, scope, purpose, record_id, now=None):
        aad = _aad(scope, purpose, record_id, self._key_id)
        self._fresh(scope, purpose, now or datetime.now(timezone.utc))
        try:
            if (type(envelope) is not dict or set(envelope) != {"aad", "nonce", "ciphertext"}
                    or _bytes(envelope["aad"]) != _bytes(aad)):
                raise ValueError()
            nonce, encrypted = envelope["nonce"], envelope["ciphertext"]
            if (type(nonce) is not str or len(nonce) != 16 or type(encrypted) is not str
                    or not 24 <= len(encrypted) <= 4 * ((MAX_PRIVATE_BYTES + 18) // 3)):
                raise ValueError()
            nonce = base64.b64decode(nonce, validate=True)
            ciphertext = base64.b64decode(encrypted, validate=True)
            if len(nonce) != 12 or not 17 <= len(ciphertext) <= MAX_PRIVATE_BYTES + 16:
                raise ValueError()
            return self._cipher.decrypt(nonce, ciphertext, _bytes(aad))
        except (ValueError, TypeError, KeyError, binascii.Error, InvalidTag, RecursionError):
            raise PrivateExecutionEnvelopeInvalid("Private HTTP envelope authentication failed") from None
