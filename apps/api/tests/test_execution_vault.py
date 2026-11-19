from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from apps.api.app.domain.quality_loop.http_execution_scope import HttpExecutionScope, HttpExecutionScopeInvalid
from apps.api.app.infrastructure.runner.execution_vault import ExecutionEnvelopeCipher, PrivateExecutionEnvelopeInvalid


NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)
SCOPE = HttpExecutionScope("project", "version", "batch", "case", "environment", 1,
    "sha256:" + "a" * 64, (NOW + timedelta(minutes=10)).isoformat())
SECRET = b'{"token":"private-test-token","password":"private-test-password"}'


def seal(cipher, purpose="credential"):
    return cipher.seal(SECRET, scope=SCOPE, purpose=purpose, record_id="author", now=NOW)


def test_envelope_hides_sensitive_content_and_uses_fresh_nonces():
    cipher = ExecutionEnvelopeCipher(b"a" * 32, "key-1")
    first, second = seal(cipher), seal(cipher)
    assert first["nonce"] != second["nonce"] and first["ciphertext"] != second["ciphertext"]
    assert "private-test" not in json.dumps(first)
    assert cipher.open(first, scope=SCOPE, purpose="credential", record_id="author", now=NOW) == SECRET


@pytest.mark.parametrize("field,value", [("project_id", "other"), ("version_id", "other"),
    ("batch_id", "other"), ("case_id", "other"), ("environment_id", "other"),
    ("environment_epoch", 2), ("inventory_hash", "sha256:" + "b" * 64),
    ("expires_at", (NOW + timedelta(hours=1)).isoformat())])
def test_capsule_cannot_be_rebound_or_have_its_lifetime_extended(field, value):
    cipher = ExecutionEnvelopeCipher(b"a" * 32, "key-1")
    envelope = seal(cipher)
    with pytest.raises(PrivateExecutionEnvelopeInvalid, match="authentication failed"):
        cipher.open(envelope, scope=replace(SCOPE, **{field: value}), purpose="credential", record_id="author", now=NOW)


@pytest.mark.parametrize("mutation", ["ciphertext", "nonce", "key", "key_id", "purpose", "record", "aad"])
def test_tampering_is_rejected_without_returning_plaintext(mutation):
    cipher = ExecutionEnvelopeCipher(b"a" * 32, "key-1")
    envelope = seal(cipher)
    if mutation in {"nonce", "ciphertext"}:
        envelope[mutation] = ("A" if envelope[mutation][0] != "A" else "B") + envelope[mutation][1:]
    if mutation == "aad":
        envelope["aad"]["scope"]["case_id"] = "other"
    if mutation in {"key", "key_id"}:
        cipher = ExecutionEnvelopeCipher((b"b" if mutation == "key" else b"a") * 32,
            "key-2" if mutation == "key_id" else "key-1")
    with pytest.raises(PrivateExecutionEnvelopeInvalid, match="authentication failed"):
        cipher.open(envelope, scope=SCOPE, purpose="evidence" if mutation == "purpose" else "credential",
            record_id="other" if mutation == "record" else "author", now=NOW)


def test_credentials_expire_but_archived_evidence_remains_decryptable_for_authorized_readers():
    cipher = ExecutionEnvelopeCipher(b"a" * 32, "key-1")
    credential, evidence = seal(cipher), seal(cipher, "evidence")
    expired = NOW + timedelta(minutes=10)
    with pytest.raises(PrivateExecutionEnvelopeInvalid, match="expired"):
        cipher.open(credential, scope=SCOPE, purpose="credential", record_id="author", now=expired)
    assert cipher.open(evidence, scope=SCOPE, purpose="evidence", record_id="author", now=expired) == SECRET
    with pytest.raises(PrivateExecutionEnvelopeInvalid, match="expired"):
        cipher.seal(SECRET, scope=SCOPE, purpose="credential", record_id="author", now=expired)


@pytest.mark.parametrize("epoch", [True, 0, -1, "1", 9007199254740992])
def test_scope_epoch_must_be_a_positive_exact_integer(epoch):
    with pytest.raises(HttpExecutionScopeInvalid):
        replace(SCOPE, environment_epoch=epoch).payload()
