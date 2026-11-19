"""Optional real storage checks; only the harness-created private test bucket."""
from dataclasses import replace
import os
from uuid import uuid4

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError
import pytest

from apps.api.app.infrastructure.runner.execution_vault import ExecutionEnvelopeCipher
from apps.api.app.infrastructure.storage.execution_snapshots import ExecutionSnapshotStorage
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage
from apps.api.tests.test_environment_lifecycle import BODY, specimen_lease


@pytest.mark.skipif(os.getenv("NASUS_TEST_OBJECT_STORAGE_MODE") != "minio",
    reason="requires explicit disposable MinIO test bucket through --minio harness")
def test_real_minio_private_encrypted_readback_without_snapshot_or_restore_claims():
    objects = ObjectStorage()
    assert objects.config.s3_enabled and objects.config.bucket.startswith("nasus-test-")
    store = ExecutionSnapshotStorage(objects, ExecutionEnvelopeCipher(os.urandom(32), "test-key"))
    lease = replace(specimen_lease(), lease_id=uuid4().hex)
    stored = store.archive(lease, uuid4().hex, "before", BODY)
    assert stored.storage_readback_verified and not stored.snapshot_verified and not stored.restore_verified
    assert store.read_verified(lease, stored) == BODY
    after_body = BODY + b"; after specimen"
    after = store.archive(lease, uuid4().hex, "after", after_body)
    assert after.object_key != stored.object_key and after.phase == "after"
    assert not after.snapshot_verified and not after.restore_verified
    assert store.read_verified(lease, after) == after_body
    wire = objects.get_bytes(f"s3://{objects.config.bucket}/{stored.object_key}", max_bytes=4096)
    assert BODY not in wire
    with pytest.raises(ClientError):
        store.archive(lease, stored.snapshot_id, "before", b"must not overwrite original bytes")
    assert store.read_verified(lease, stored) == BODY
    anonymous = boto3.client("s3", endpoint_url=objects.config.endpoint, region_name=objects.config.region,
        config=Config(signature_version=UNSIGNED, connect_timeout=5, read_timeout=10,
                      retries={"mode": "standard", "total_max_attempts": 1}))
    try:
        with pytest.raises(ClientError) as denied:
            anonymous.get_object(Bucket=objects.config.bucket, Key=stored.object_key)
        assert denied.value.response["ResponseMetadata"]["HTTPStatusCode"] == 403
    finally:
        anonymous.close()
