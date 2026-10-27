"""Real private MinIO access; opt in through the isolated PG/S3 test runner."""
import os
from uuid import uuid4

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError
import pytest

from apps.api.app.infrastructure.storage.object_storage import ObjectStorage


@pytest.mark.skipif(os.getenv("NASUS_TEST_OBJECT_STORAGE_MODE") != "minio",
    reason="requires the explicit disposable MinIO test bucket")
def test_live_private_test_bucket_denies_anonymous_source_downloads():
    storage = ObjectStorage()
    config = storage.config
    assert config.s3_enabled and config.bucket.startswith("nasus-test-")
    payload = b"private-system-image-test-source"
    stored = storage.put_bytes(f"system-image/tests/{uuid4().hex}", payload, content_type="text/plain")
    assert stored.backend == "s3" and stored.storage_ref.startswith(f"s3://{config.bucket}/")
    assert storage.get_bytes(stored.storage_ref) == payload
    anonymous = boto3.client("s3", endpoint_url=config.endpoint, region_name=config.region,
        config=Config(signature_version=UNSIGNED, connect_timeout=5, read_timeout=10,
            retries={"mode": "standard", "total_max_attempts": 1}))
    try:
        with pytest.raises(ClientError) as denied:
            anonymous.get_object(Bucket=config.bucket, Key=stored.key)
        assert denied.value.response["ResponseMetadata"]["HTTPStatusCode"] == 403
        assert denied.value.response["Error"]["Code"] == "AccessDenied"
    finally:
        anonymous.close()
