"""Encrypted, batch-bound, private MinIO archives; never a database dump adapter.

Storage readback proves only transport integrity. Snapshot validity and restored
state stay false here; only the separately controlled target can prove those.
Bucket configuration and cipher keys must come from operator composition.
"""
from dataclasses import replace
import hashlib
import json

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError

from ...domain.quality_loop.execution_environment_lifecycle import (
    BatchSnapshotScope, EnvironmentLifecycleInvalid, MAX_SNAPSHOT_BYTES,
    StoredExecutionSnapshot, identity,
)
from ..runner.execution_vault import ExecutionEnvelopeCipher
from .object_storage import ObjectStorage


def _hash(body):
    return "sha256:" + hashlib.sha256(body).hexdigest()


class ExecutionSnapshotStorage:
    def __init__(self, storage: ObjectStorage, cipher: ExecutionEnvelopeCipher, *, anonymous_client_factory=None):
        if not storage.config.s3_enabled:
            raise EnvironmentLifecycleInvalid("Private snapshots require configured MinIO/S3, not local fallback")
        self.storage, self.cipher = storage, cipher
        self._anonymous_client_factory = anonymous_client_factory or self._anonymous_client

    def _anonymous_client(self):
        return boto3.client("s3", endpoint_url=self.storage.config.endpoint, region_name=self.storage.config.region,
            config=Config(signature_version=UNSIGNED, connect_timeout=5, read_timeout=10,
                          retries={"mode": "standard", "total_max_attempts": 1}))

    def _deny_anonymous(self, key):
        client = self._anonymous_client_factory()
        try:
            try:
                response = client.get_object(Bucket=self.storage.config.bucket, Key=key, Range="bytes=0-0")
            except ClientError as error:
                if (error.response.get("Error", {}).get("Code") != "AccessDenied"
                        or error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 403):
                    raise EnvironmentLifecycleInvalid("Anonymous snapshot denial could not be verified") from None
            else:
                response["Body"].close()
                raise EnvironmentLifecycleInvalid("Snapshot is anonymously readable")
        finally:
            client.close()

    def _private(self):
        # Fail closed even on policy/ACL inspection errors. A dedicated no-policy,
        # owner-only bucket is intentionally stricter than parsing arbitrary IAM.
        with self.storage._s3_read_client() as client:
            try:
                client.get_bucket_policy(Bucket=self.storage.config.bucket)
            except ClientError as error:
                if error.response.get("Error", {}).get("Code") != "NoSuchBucketPolicy":
                    raise EnvironmentLifecycleInvalid("Snapshot bucket privacy cannot be established") from None
            else:
                raise EnvironmentLifecycleInvalid("Snapshot bucket must have no sharing policy")
            acl = client.get_bucket_acl(Bucket=self.storage.config.bucket)
            owner = acl.get("Owner", {}).get("ID")
            grants = acl.get("Grants")
            # MinIO's canned private ACL omits canonical IDs. Accept that shape
            # only alongside the no-policy check and actual unsigned read denial.
            ownerless = (not owner and type(grants) is list and len(grants) == 1
                         and grants[0].get("Grantee", {}).get("Type") == "CanonicalUser"
                         and not grants[0].get("Grantee", {}).get("ID")
                         and grants[0].get("Permission") == "FULL_CONTROL")
            if not ownerless and (not owner or type(grants) is not list or not grants
                    or any(grant.get("Grantee", {}).get("Type") != "CanonicalUser"
                           or grant.get("Grantee", {}).get("ID") != owner for grant in grants)):
                raise EnvironmentLifecycleInvalid("Snapshot bucket must be owner-only")

    @staticmethod
    def _key(lease, snapshot_id, phase):
        identity(snapshot_id)
        scope = json.dumps(BatchSnapshotScope.from_lease(lease, phase).payload(), sort_keys=True, separators=(",", ":")).encode()
        return "private/execution-snapshots/" + hashlib.sha256(scope).hexdigest() + "/" + snapshot_id + ".json"

    def archive(self, lease, snapshot_id, phase, body):
        if type(body) is not bytes or not 1 <= len(body) <= min(lease.max_snapshot_bytes, MAX_SNAPSHOT_BYTES):
            raise EnvironmentLifecycleInvalid("Snapshot exceeds its byte bound")
        key = self._key(lease, snapshot_id, phase)
        self._private()
        envelope = self.cipher.seal(body, scope=BatchSnapshotScope.from_lease(lease, phase),
                                   purpose="snapshot", record_id=snapshot_id)
        encrypted = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
        with self.storage._s3_write_client() as client:
            client.put_object(Bucket=self.storage.config.bucket, Key=key, Body=encrypted,
                ContentLength=len(encrypted), ContentType="application/json", IfNoneMatch="*",
                Metadata={"nasus-content-hash": _hash(encrypted)})
        receipt = StoredExecutionSnapshot(snapshot_id, lease.lease_id, lease.generation, phase, key,
            _hash(body), _hash(encrypted), len(body))
        # Verification must read the stored bytes, not the in-memory upload body.
        self._read(lease, receipt)
        return replace(receipt, storage_readback_verified=True)

    def _read(self, lease, snapshot):
        expected = self._key(lease, snapshot.snapshot_id, snapshot.phase)
        if (snapshot.object_key != expected or snapshot.lease_id != lease.lease_id
                or snapshot.generation != lease.generation):
            raise EnvironmentLifecycleInvalid("Snapshot cannot be rebound to another batch or fence")
        self._private()
        self._deny_anonymous(expected)
        encrypted = self.storage.get_bytes(f"s3://{self.storage.config.bucket}/{expected}",
            max_bytes=4 * ((lease.max_snapshot_bytes + 18) // 3) + 4096)
        if _hash(encrypted) != snapshot.encrypted_hash:
            raise EnvironmentLifecycleInvalid("Encrypted snapshot checksum differs")
        envelope = json.loads(encrypted)
        body = self.cipher.open(envelope, scope=BatchSnapshotScope.from_lease(lease, snapshot.phase),
                                purpose="snapshot", record_id=snapshot.snapshot_id)
        if (not 1 <= len(body) <= lease.max_snapshot_bytes or len(body) != snapshot.size_bytes
                or _hash(body) != snapshot.content_hash):
            raise EnvironmentLifecycleInvalid("Snapshot plaintext checksum differs")
        return body

    def read_verified(self, lease, snapshot):
        snapshot.require(lease)
        return self._read(lease, snapshot)
