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


@pytest.mark.skipif(os.getenv("NASUS_TEST_OBJECT_STORAGE_MODE") != "minio",
    reason="requires the explicit disposable MinIO test bucket")
def test_live_minio_reuses_write_connection_across_empty_source_files(caplog):
    storage = ObjectStorage()
    assert storage.config.bucket.startswith("nasus-test-")
    objects = []
    with storage.write_session():
        for payload in (b"before", b"", b"", b"after", b"", b"last"):
            objects.append((storage.put_bytes(f"empty-source-test/{uuid4().hex}", payload), payload))
    with storage.read_session():
        for stored, payload in objects:
            assert storage.get_bytes(stored.storage_ref) == payload
    assert "Failed to parse headers" not in caplog.text


@pytest.mark.parametrize("size,expected", [("0", False), (0, False), ("10", True), (None, True)])
def test_empty_continue_hook_is_limited_to_known_zero_length(size, expected):
    from types import SimpleNamespace
    from apps.api.app.infrastructure.storage.object_storage import _omit_empty_continue
    headers = {"Expect": "100-continue", "X-Amz-Checksum-Crc32": "intact"}
    if size is not None:
        headers["Content-Length"] = size
    _omit_empty_continue(SimpleNamespace(headers=headers))
    assert ("Expect" in headers) is expected
    assert headers["X-Amz-Checksum-Crc32"] == "intact"
