"""An explicitly selected local S3 test bucket, separate from developer data."""
from __future__ import annotations

from contextlib import contextmanager
from urllib.parse import urlsplit
from uuid import uuid4


def _client(settings):
    import boto3
    from botocore.config import Config

    return boto3.client("s3", endpoint_url=settings["endpoint"],
        aws_access_key_id=settings["access_key"], aws_secret_access_key=settings["secret_key"],
        region_name="us-east-1", config=Config(connect_timeout=5, read_timeout=30,
            retries={"mode": "standard", "total_max_attempts": 2}))


def _settings(environment):
    endpoint = environment.get("NASUS_TEST_S3_ENDPOINT", "")
    parsed = urlsplit(endpoint)
    if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError("NASUS_TEST_S3_ENDPOINT must be an explicitly configured local S3 server")
    parsed.port  # Reject malformed port numbers before creating a client.
    access_key = environment.get("NASUS_TEST_S3_ACCESS_KEY")
    secret_key = environment.get("NASUS_TEST_S3_SECRET_KEY")
    if not access_key or not secret_key:
        raise ValueError("explicit NASUS_TEST_S3_ACCESS_KEY and NASUS_TEST_S3_SECRET_KEY are required")
    return {"endpoint": endpoint, "access_key": access_key, "secret_key": secret_key}


def _cleanup(client, bucket):
    # Delete from the beginning each time: deleting a page can invalidate an
    # object-list cursor. Only the bucket successfully created here is owned.
    for _ in range(1000):
        objects = client.list_objects_v2(Bucket=bucket, MaxKeys=1000).get("Contents", [])
        if not objects:
            client.delete_bucket(Bucket=bucket)
            return
        result = client.delete_objects(Bucket=bucket,
            Delete={"Objects": [{"Key": item["Key"]} for item in objects], "Quiet": True})
        if result.get("Errors"):
            raise RuntimeError("isolated test bucket object cleanup failed")
    raise RuntimeError("isolated test bucket cleanup exceeded its bound")


@contextmanager
def isolated_test_storage(environment, *, client_factory=None):
    settings = _settings(environment)
    bucket = "nasus-test-" + uuid4().hex
    client = (client_factory or _client)(settings)
    created = False
    try:
        client.create_bucket(Bucket=bucket, ACL="private")
        created = True
        yield {"NASUS_S3_ENDPOINT": settings["endpoint"], "NASUS_S3_BUCKET": bucket,
            "NASUS_S3_ACCESS_KEY": settings["access_key"], "NASUS_S3_SECRET_KEY": settings["secret_key"],
            "NASUS_S3_REGION": "us-east-1", "NASUS_TEST_OBJECT_STORAGE_MODE": "minio"}
    finally:
        try:
            if created:
                _cleanup(client, bucket)
        finally:
            client.close()
