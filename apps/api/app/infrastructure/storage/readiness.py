from __future__ import annotations

import os

from .object_storage import ObjectStorage


class ObjectStorageReadinessProbe:
    name = "object_storage"

    def __init__(self, storage: ObjectStorage) -> None:
        self._storage = storage

    def check(self) -> dict[str, str]:
        config = self._storage.config
        if config.s3_enabled:
            client = self._s3_client()
            client.head_bucket(Bucket=config.bucket)
            return {"backend": "s3", "bucket": config.bucket}

        bucket_dir = config.local_dir / config.bucket
        bucket_dir.mkdir(parents=True, exist_ok=True)
        if not os.access(bucket_dir, os.R_OK | os.W_OK):
            raise PermissionError(f"local object storage is not readable and writable: {bucket_dir}")
        return {"backend": "local", "bucket": config.bucket}

    def _s3_client(self):
        try:
            import boto3  # type: ignore[import-not-found]
            from botocore.config import Config
        except ModuleNotFoundError as exc:
            raise RuntimeError("S3 object storage is configured but boto3 is not installed") from exc

        config = self._storage.config
        return boto3.client(
            "s3",
            endpoint_url=config.endpoint,
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key,
            region_name=config.region,
            config=Config(
                connect_timeout=2,
                read_timeout=2,
                retries={"max_attempts": 1, "mode": "standard"},
            ),
        )


__all__ = ["ObjectStorageReadinessProbe"]
