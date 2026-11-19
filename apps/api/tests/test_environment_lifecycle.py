"""Synthetic protocol specimens only: no business execution, dump, or reset."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from types import SimpleNamespace

from botocore.exceptions import ClientError
import pytest

from apps.api.app.application.quality_loop.environment_lifecycle import EnvironmentLifecycleService
from apps.api.app.domain.quality_loop.execution_environment_lifecycle import (
    BaselineResetVerification, BatchSnapshotScope, CleanBaselineVerification, EnvironmentFenceRejected, EnvironmentLease,
    EnvironmentLifecycleInvalid, EnvironmentOperationFailed, ExecutionStoppedProof,
    IndependentRestoreVerification, MAX_LEASE_SECONDS, RegisteredExecutionEnvironment,
    SNAPSHOT_SCHEMA, SnapshotVerification,
)
from apps.api.app.infrastructure.runner.execution_vault import ExecutionEnvelopeCipher, PrivateExecutionEnvelopeInvalid
from apps.api.app.infrastructure.storage.execution_snapshots import ExecutionSnapshotStorage


BODY = b"synthetic protocol specimen; not a database snapshot"
CONTENT_HASH = "sha256:" + hashlib.sha256(BODY).hexdigest()
NOW = datetime(2026, 11, 18, tzinfo=timezone.utc)


def specimen_lease(**changes):
    return replace(EnvironmentLease("lease", "environment", "project", "version", "batch", "owner", 1,
        "registered-target", "sha256:" + "a" * 64, NOW, NOW + timedelta(seconds=60), 1024), **changes)


class SpecimenObjects:
    """In-memory S3 protocol double; never claims real MinIO evidence."""
    def __init__(self):
        self.config = SimpleNamespace(s3_enabled=True, bucket="nasus-test-snapshot-specimen")
        self.objects, self.reads, self.puts = {}, 0, 0
        self.policy, self.shared, self.corrupt, self.privacy_error = False, False, False, False
        self.public, self.anonymous_error, self.ownerless = False, False, False

    @contextmanager
    def _s3_read_client(self):
        yield self

    _s3_write_client = _s3_read_client

    def get_bucket_policy(self, **kwargs):
        if self.privacy_error:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetBucketPolicy")
        if self.policy:
            return {"Policy": "{}"}
        raise ClientError({"Error": {"Code": "NoSuchBucketPolicy"}}, "GetBucketPolicy")

    def get_bucket_acl(self, **kwargs):
        if self.ownerless:
            return {"Owner": {"ID": ""}, "Grants": [{"Grantee": {"Type": "CanonicalUser"}, "Permission": "FULL_CONTROL"}]}
        return {"Owner": {"ID": "owner"}, "Grants": [{"Grantee": {
            "ID": "owner", "Type": "Group" if self.shared else "CanonicalUser"}, "Permission": "FULL_CONTROL"}]}

    def get_object(self, **kwargs):
        if self.public:
            return {"Body": io.BytesIO(b"x")}
        code, status = ("NoSuchKey", 404) if self.anonymous_error else ("AccessDenied", 403)
        raise ClientError({"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}, "GetObject")

    def close(self):
        pass

    def put_object(self, *, Bucket, Key, Body, IfNoneMatch, **kwargs):
        assert Bucket == self.config.bucket and IfNoneMatch == "*"
        if Key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.objects[Key] = Body
        self.puts += 1

    def get_bytes(self, ref, *, max_bytes):
        prefix = "s3://" + self.config.bucket + "/"
        assert ref.startswith(prefix)
        self.reads += 1
        body = self.objects[ref.removeprefix(prefix)]
        if self.corrupt:
            body += b" "
        if len(body) > max_bytes:
            raise ValueError("bounded read rejected")
        return body


class SpecimenRepository:
    def __init__(self, lease):
        self.lease, self.phase, self.archived, self.reset_verified = lease, "leased", {}, False
        self.restores, self.baseline_verified = {}, False
        self.reason = None

    def acquire(self, **kwargs):
        return self.lease

    def require_live(self, lease, *, phases):
        if lease != self.lease or self.phase not in phases:
            raise EnvironmentFenceRejected("specimen fence rejected")

    def transition(self, lease, *, expected, phase, stopped=None):
        self.require_live(lease, phases=expected)
        self.phase = phase

    def record_snapshot(self, lease, snapshot):
        self.require_live(lease, phases=("capturing_" + snapshot.phase,))
        self.archived[snapshot.phase] = snapshot

    def record_baseline(self, lease, proof):
        proof.require(lease)
        self.baseline_verified = True

    def snapshot(self, lease, phase):
        return self.archived[phase]

    def record_independent_restore(self, lease, proof):
        self.restores[proof.phase] = proof
        self.phase = proof.phase + "_ready"

    def restore_verification(self, lease, phase):
        return self.restores[phase]

    def record_reset(self, lease, proof):
        self.require_live(lease, phases=("resetting",))
        self.phase, self.reset_verified = "reset_complete", proof.clean_baseline_verified

    def quarantine(self, lease, *, reason):
        self.phase, self.reason = "quarantined", reason

    def release(self, lease):
        self.require_live(lease, phases=("leased", "reset_complete"))
        self.phase = "released"


class SpecimenTarget:
    """Explicit test-only proofs. No implementation invokes any external process."""
    def __init__(self):
        self.calls, self.failure, self.stopped = [], None, True
        self.snapshot_valid, self.restored = True, True
        self.clean, self.reset_clean, self.independent, self.unchanged = True, True, True, True
        self.body = BODY

    def _call(self, name):
        self.calls.append(name)
        if self.failure == name:
            raise RuntimeError("private-password-must-not-be-retained")

    def resolve(self, target_key):
        assert target_key == "registered-target"
        return self

    def stop_and_fence(self, lease):
        self._call("stop")
        return ExecutionStoppedProof(lease.lease_id, lease.generation, "specimen-stop", self.stopped)

    def capture(self, lease, stopped, *, max_bytes):
        stopped.require(lease)
        self._call("capture")
        return self.body

    def verify_clean_baseline(self, lease, stopped):
        stopped.require(lease)
        self._call("baseline")
        return CleanBaselineVerification(lease.lease_id, lease.generation, "specimen-baseline", self.clean, True)

    def verify_snapshot(self, lease, snapshot_id, phase, body):
        self._call("verify")
        return SnapshotVerification(lease.lease_id, lease.generation, snapshot_id,
            "sha256:" + hashlib.sha256(body).hexdigest(), phase, self.snapshot_valid,
            "specimen-snapshot" if self.snapshot_valid else None)

    def restore_to_independent_copy(self, lease, snapshot, body):
        self._call("independent_restore")
        return IndependentRestoreVerification(lease.lease_id, lease.generation, snapshot.snapshot_id,
            snapshot.content_hash, snapshot.phase, self.restored, "copy-" + snapshot.snapshot_id,
            "independent-" + snapshot.snapshot_id if self.independent else lease.target_key, self.independent, self.unchanged)

    def reset_to_clean_baseline(self, lease, before, after, before_body, stopped):
        stopped.require(lease)
        assert before_body == BODY
        self._call("reset")
        return BaselineResetVerification(lease.lease_id, lease.generation, "specimen-reset", self.reset_clean, True,
                                          before.snapshot_id, after.snapshot_id)


class SpecimenAccess:
    def __init__(self):
        self.allowed = True

    def require_access(self, **kwargs):
        if not self.allowed:
            raise PermissionError("revoked")


@pytest.fixture
def specimen():
    lease = specimen_lease()
    repo, target, objects, access = SpecimenRepository(lease), SpecimenTarget(), SpecimenObjects(), SpecimenAccess()
    store = ExecutionSnapshotStorage(objects, ExecutionEnvelopeCipher(b"x" * 32, "test-key"),
                                     anonymous_client_factory=lambda: objects)
    service = EnvironmentLifecycleService(repository=repo, access=access, snapshots=store, targets=target)
    return SimpleNamespace(lease=lease, repo=repo, target=target, objects=objects, access=access, store=store, service=service)


def capture_specimen(v):
    v.service.capture(v.lease, phase="before")
    v.service.mark_running(v.lease)
    v.service.stop(v.lease)
    return v.service.capture(v.lease, phase="after")


def test_batch_aad_is_distinct_encrypted_and_has_no_invented_case(specimen):
    v = specimen
    stored = v.store.archive(v.lease, "snapshot", "before", BODY)
    wire = v.objects.objects[stored.object_key]
    envelope = json.loads(wire)
    assert BODY not in wire
    assert envelope["aad"]["schema"] == SNAPSHOT_SCHEMA
    assert envelope["aad"]["purpose"] == "snapshot"
    assert "case_id" not in envelope["aad"]["scope"]
    assert stored.storage_readback_verified is True
    assert stored.snapshot_verified is False and stored.restore_verified is False
    assert v.objects.reads == 1
    assert v.store.read_verified(v.lease, stored) == BODY
    with pytest.raises(ClientError):
        v.store.archive(v.lease, "snapshot", "before", b"replacement")
    assert v.objects.objects[stored.object_key] == wire


@pytest.mark.parametrize("field,value", [("project_id", "other"), ("version_id", "other"),
    ("batch_id", "other"), ("environment_id", "other"), ("lease_id", "other"),
    ("generation", 2), ("inventory_hash", "sha256:" + "b" * 64),
    ("expires_at", (NOW + timedelta(seconds=90)).isoformat()), ("phase", "after")])
def test_batch_scope_cannot_be_rebound(specimen, field, value):
    v = specimen
    scope = BatchSnapshotScope.from_lease(v.lease, "before")
    envelope = v.store.cipher.seal(BODY, scope=scope, purpose="snapshot", record_id="snapshot")
    with pytest.raises(PrivateExecutionEnvelopeInvalid):
        v.store.cipher.open(envelope, scope=replace(scope, **{field: value}), purpose="snapshot", record_id="snapshot")


@pytest.mark.parametrize("purpose", ["evidence", "credential"])
def test_snapshot_is_not_http_evidence_or_credential(specimen, purpose):
    with pytest.raises(PrivateExecutionEnvelopeInvalid):
        specimen.store.cipher.seal(BODY, scope=BatchSnapshotScope.from_lease(specimen.lease, "before"), purpose=purpose, record_id="s")


@pytest.mark.parametrize("fault", ["policy", "shared", "privacy_error"])
def test_private_bucket_is_required_before_any_write(specimen, fault):
    setattr(specimen.objects, fault, True)
    with pytest.raises(EnvironmentLifecycleInvalid):
        specimen.store.archive(specimen.lease, "snapshot", "before", BODY)
    assert specimen.objects.puts == 0


def test_no_local_storage_fallback(specimen):
    specimen.objects.config.s3_enabled = False
    with pytest.raises(EnvironmentLifecycleInvalid):
        ExecutionSnapshotStorage(specimen.objects, specimen.store.cipher)


def test_verified_readback_not_upload_success_is_required(specimen):
    specimen.objects.corrupt = True
    with pytest.raises(EnvironmentLifecycleInvalid, match="checksum"):
        specimen.store.archive(specimen.lease, "snapshot", "before", BODY)
    assert specimen.objects.puts == 1 and specimen.objects.reads == 1


@pytest.mark.parametrize("fault", ["public", "anonymous_error"])
def test_unsigned_object_read_must_be_denied_not_merely_fail(specimen, fault):
    setattr(specimen.objects, fault, True)
    with pytest.raises(EnvironmentLifecycleInvalid):
        specimen.store.archive(specimen.lease, "snapshot", "before", BODY)


def test_minio_ownerless_private_acl_requires_unsigned_denial(specimen):
    specimen.objects.ownerless = True
    assert specimen.store.archive(specimen.lease, "snapshot", "before", BODY).storage_readback_verified
    specimen.objects.public = True
    with pytest.raises(EnvironmentLifecycleInvalid):
        specimen.store.archive(specimen.lease, "another", "before", BODY)


@pytest.mark.parametrize("field,value", [("object_key", "../other"), ("encrypted_hash", "sha256:" + "0" * 64),
    ("content_hash", "sha256:" + "0" * 64), ("size_bytes", 1), ("generation", 2), ("lease_id", "other")])
def test_readback_rejects_tampered_receipt(specimen, field, value):
    stored = specimen.store.archive(specimen.lease, "snapshot", "before", BODY)
    with pytest.raises(EnvironmentLifecycleInvalid):
        specimen.store.read_verified(specimen.lease, replace(stored, **{field: value}))


def test_ciphertext_authentication_is_checked_even_if_checksum_was_changed(specimen):
    v = specimen
    stored = v.store.archive(v.lease, "snapshot", "before", BODY)
    wire = json.loads(v.objects.objects[stored.object_key])
    wire["ciphertext"] = ("A" if wire["ciphertext"][0] != "A" else "B") + wire["ciphertext"][1:]
    changed = json.dumps(wire).encode()
    v.objects.objects[stored.object_key] = changed
    with pytest.raises(PrivateExecutionEnvelopeInvalid):
        v.store.read_verified(v.lease, replace(stored, encrypted_hash="sha256:" + hashlib.sha256(changed).hexdigest()))


def test_full_protocol_specimen_requires_new_stopped_proof_before_reset(specimen):
    v = specimen
    archived = capture_specimen(v)
    assert archived.snapshot_verified and archived.restore_verified
    assert archived.archive.restore_verified is False and not v.repo.reset_verified
    proof = v.service.reset(v.lease)
    assert proof.clean_baseline_verified and v.repo.reset_verified
    assert v.target.calls == ["stop", "baseline", "capture", "verify", "independent_restore",
                              "stop", "stop", "capture", "verify", "independent_restore", "stop", "reset"]
    assert v.objects.reads == 6
    v.service.release(v.lease)
    assert v.repo.phase == "released"


@pytest.mark.parametrize("operation", ["capture", "reset", "release"])
def test_running_execution_cannot_capture_reset_or_release(specimen, operation):
    v = specimen
    v.service.capture(v.lease, phase="before")
    v.service.mark_running(v.lease)
    v.target.calls.clear()
    prior_puts = v.objects.puts
    with pytest.raises(EnvironmentFenceRejected):
        if operation == "capture":
            v.service.capture(v.lease, phase="after")
        else:
            getattr(v.service, operation)(v.lease)
    assert v.target.calls == [] and v.objects.puts == prior_puts


@pytest.mark.parametrize("failure", ["stop", "capture", "verify", "reset"])
def test_operation_failure_quarantines_without_retaining_exception_secrets(specimen, failure):
    v = specimen
    if failure == "reset":
        capture_specimen(v)
    elif failure == "stop":
        v.service.capture(v.lease, phase="before")
        v.service.mark_running(v.lease)
    v.target.failure = failure
    with pytest.raises(EnvironmentOperationFailed) as error:
        if failure == "stop":
            v.service.stop(v.lease)
        elif failure == "reset":
            v.service.reset(v.lease)
        else:
            v.service.capture(v.lease, phase="before")
    assert v.repo.phase == "quarantined"
    assert "private-password" not in str(error.value) + str(v.repo.reason)
    assert not v.repo.reset_verified
    if failure == "verify":
        assert v.repo.archived["before"].storage_readback_verified
        assert not v.repo.archived["before"].snapshot_verified


def test_unproved_snapshot_is_retained_but_never_grants_reset(specimen):
    v = specimen
    v.target.snapshot_valid = False
    with pytest.raises(EnvironmentOperationFailed):
        capture_specimen(v)
    assert v.repo.archived["before"].storage_readback_verified
    assert not v.repo.archived["before"].snapshot_verified and not v.repo.archived["before"].restore_verified
    assert v.repo.phase == "quarantined" and "reset" not in v.target.calls


@pytest.mark.parametrize("fault", ["running_again", "corrupt_archive", "reset_unproved"])
def test_reset_fails_closed_when_a_guard_changes(specimen, fault):
    v = specimen
    capture_specimen(v)
    if fault == "running_again":
        v.target.stopped = False
    elif fault == "corrupt_archive":
        v.objects.corrupt = True
    else:
        v.target.reset_clean = False
    with pytest.raises(EnvironmentOperationFailed):
        v.service.reset(v.lease)
    assert v.repo.phase == "quarantined" and not v.repo.reset_verified
    assert ("reset" in v.target.calls) == (fault == "reset_unproved")


def test_access_rechecked_after_external_call_and_before_archive(specimen, monkeypatch):
    v = specimen
    original = v.target.capture

    def revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        v.access.allowed = False
        return result

    monkeypatch.setattr(v.target, "capture", revoke)
    with pytest.raises(EnvironmentOperationFailed):
        v.service.capture(v.lease, phase="before")
    assert v.objects.puts == 0 and v.repo.phase == "quarantined"


@pytest.mark.parametrize("body", [b"", b"x" * 1025, "not-bytes"])
def test_capture_size_bound_is_enforced_before_upload(specimen, body):
    specimen.target.body = body
    with pytest.raises(EnvironmentOperationFailed):
        capture_specimen(specimen)
    assert specimen.objects.puts == 0


@pytest.mark.parametrize("key", ["http://localhost", "DROP TABLE orders", "container/target", "../target", ""])
def test_registration_accepts_opaque_ids_not_connection_or_command_text(key):
    with pytest.raises(EnvironmentLifecycleInvalid):
        RegisteredExecutionEnvironment("environment", "project", key, "sha256:" + "a" * 64)


def test_proof_defaults_do_not_claim_real_verification():
    lease = specimen_lease()
    with pytest.raises(EnvironmentFenceRejected):
        ExecutionStoppedProof(lease.lease_id, lease.generation, "proof").require(lease)
    assert not SnapshotVerification(lease.lease_id, lease.generation, "snapshot", CONTENT_HASH, "before").verified
    proof = IndependentRestoreVerification(lease.lease_id, lease.generation, "snapshot", CONTENT_HASH, "before")
    assert not proof.verified and not proof.independent_copy_verified
    assert not BaselineResetVerification(lease.lease_id, lease.generation, "proof").clean_baseline_verified
    with pytest.raises(EnvironmentLifecycleInvalid):
        specimen_lease(expires_at=NOW + timedelta(seconds=MAX_LEASE_SECONDS + 1))


@pytest.mark.parametrize("generation", [True, 1.0, "1", 0, -1])
def test_proof_generation_must_be_an_exact_positive_integer(generation):
    lease = specimen_lease()
    with pytest.raises(EnvironmentLifecycleInvalid):
        ExecutionStoppedProof(lease.lease_id, generation, "proof", True).require(lease)
    with pytest.raises(EnvironmentLifecycleInvalid):
        SnapshotVerification(lease.lease_id, generation, "snapshot", CONTENT_HASH, "before", True, "proof").require_scope(
            lease, "snapshot", CONTENT_HASH, "before")


def test_execution_cannot_start_without_clean_verified_before_snapshot(specimen):
    with pytest.raises(EnvironmentFenceRejected):
        specimen.service.mark_running(specimen.lease)
    assert specimen.target.calls == []


def test_readable_dump_does_not_prove_initial_clean_baseline(specimen):
    v = specimen
    v.target.clean = False
    with pytest.raises(EnvironmentOperationFailed):
        v.service.capture(v.lease, phase="before")
    assert "capture" not in v.target.calls and v.objects.puts == 0
    assert v.repo.phase == "quarantined" and not v.repo.baseline_verified


@pytest.mark.parametrize("phase", ["before", "after"])
@pytest.mark.parametrize("fault", ["restored", "independent", "unchanged"])
def test_each_snapshot_requires_its_own_source_unchanged_independent_restore(specimen, phase, fault):
    v = specimen
    if phase == "after":
        v.service.capture(v.lease, phase="before")
        v.service.mark_running(v.lease)
        v.service.stop(v.lease)
    setattr(v.target, fault, False)
    with pytest.raises(EnvironmentOperationFailed):
        v.service.capture(v.lease, phase=phase)
    assert v.repo.phase == "quarantined" and phase not in v.repo.restores
    assert v.repo.archived[phase].snapshot_verified
    assert not v.repo.archived[phase].restore_verified and not v.repo.reset_verified
    assert "reset" not in v.target.calls


def test_before_and_after_proofs_cannot_be_interchanged_or_count_as_reset(specimen):
    v = specimen
    after = capture_specimen(v)
    before_archive = v.repo.archived["before"]
    before_restore = v.repo.restores["before"]
    assert before_restore.proof_id != after.independent_restore.proof_id
    assert before_restore.independent_target_key != after.independent_restore.independent_target_key
    with pytest.raises(EnvironmentFenceRejected):
        before_restore.require(v.lease, after.archive)
    with pytest.raises(EnvironmentFenceRejected):
        after.independent_restore.require(v.lease, before_archive)
    assert not v.repo.reset_verified


@pytest.mark.parametrize("phase", ["middle", "", None, 1])
def test_only_two_snapshot_phases_are_permitted(specimen, phase):
    with pytest.raises(EnvironmentLifecycleInvalid):
        specimen.service.capture(specimen.lease, phase=phase)
    assert not specimen.target.calls and not specimen.objects.objects
