from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ObjectStoragePutResult:
    storage_ref: str
    content_hash: str
    backend: str
    key: str


@dataclass(frozen=True)
class ObjectStorageConfig:
    endpoint: str | None
    bucket: str
    access_key: str | None
    secret_key: str | None
    region: str
    local_dir: Path

    @classmethod
    def from_env(cls) -> "ObjectStorageConfig":
        return cls(
            endpoint=os.getenv("NASUS_S3_ENDPOINT") or None,
            bucket=os.getenv("NASUS_S3_BUCKET", "nasus-artifacts"),
            access_key=os.getenv("NASUS_S3_ACCESS_KEY") or os.getenv("MINIO_ROOT_USER") or None,
            secret_key=os.getenv("NASUS_S3_SECRET_KEY") or os.getenv("MINIO_ROOT_PASSWORD") or None,
            region=os.getenv("NASUS_S3_REGION", "us-east-1"),
            local_dir=Path(os.getenv("NASUS_OBJECT_STORE_DIR", ".nasus/object-store")),
        )

    @property
    def s3_enabled(self) -> bool:
        return bool(self.endpoint and self.bucket and self.access_key and self.secret_key)


class ObjectStorage:
    """Small S3-compatible object storage adapter.

    Local tests use filesystem-backed refs. Deployments with NASUS_S3_* env vars
    use MinIO/S3 through boto3, keeping API code independent from the concrete
    object store implementation.
    """

    def __init__(self, config: ObjectStorageConfig | None = None) -> None:
        self.config = config or ObjectStorageConfig.from_env()

    def put_json(self, key: str, payload: dict[str, Any]) -> ObjectStoragePutResult:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return self.put_bytes(key, body, content_type="application/json")

    def get_json(self, storage_ref: str) -> dict[str, Any]:
        body = self.get_bytes(storage_ref)
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"object payload is not a JSON object: {storage_ref}")
        return payload

    def get_bytes(self, storage_ref: str, *, max_bytes: int | None = None) -> bytes:
        if storage_ref.startswith("local-object://"):
            bucket_and_key = storage_ref.removeprefix("local-object://")
            bucket, _, key = bucket_and_key.partition("/")
            if not bucket or not key:
                raise ValueError(f"invalid local object ref: {storage_ref}")
            path = self.config.local_dir / bucket / self._normalize_key(key)
            if max_bytes is not None and path.stat().st_size > max_bytes:
                raise ValueError(f"object exceeds max bytes {max_bytes}: {storage_ref}")
            return path.read_bytes()
        if storage_ref.startswith("s3://"):
            bucket_and_key = storage_ref.removeprefix("s3://")
            bucket, _, key = bucket_and_key.partition("/")
            if not bucket or not key:
                raise ValueError(f"invalid s3 object ref: {storage_ref}")
            return self._get_s3(bucket, self._normalize_key(key), max_bytes=max_bytes)
        raise ValueError(f"unsupported object storage ref: {storage_ref}")

    def put_bytes(self, key: str, body: bytes, *, content_type: str = "application/octet-stream") -> ObjectStoragePutResult:
        normalized_key = self._normalize_key(key)
        content_hash = f"sha256:{hashlib.sha256(body).hexdigest()}"
        if self.config.s3_enabled:
            self._put_s3(normalized_key, body, content_type=content_type, content_hash=content_hash)
            return ObjectStoragePutResult(
                storage_ref=f"s3://{self.config.bucket}/{normalized_key}",
                content_hash=content_hash,
                backend="s3",
                key=normalized_key,
            )

        target = self.config.local_dir / self.config.bucket / normalized_key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        return ObjectStoragePutResult(
            storage_ref=f"local-object://{self.config.bucket}/{normalized_key}",
            content_hash=content_hash,
            backend="local",
            key=normalized_key,
        )

    def _put_s3(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str,
        content_hash: str,
    ) -> None:
        try:
            import boto3  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            raise RuntimeError("S3 object storage is configured but boto3 is not installed") from exc

        client = boto3.client(
            "s3",
            endpoint_url=self.config.endpoint,
            aws_access_key_id=self.config.access_key,
            aws_secret_access_key=self.config.secret_key,
            region_name=self.config.region,
        )
        client.put_object(
            Bucket=self.config.bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            Metadata={"nasus-content-hash": content_hash},
        )

    def _get_s3(self, bucket: str, key: str, *, max_bytes: int | None = None) -> bytes:
        try:
            import boto3  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            raise RuntimeError("S3 object storage is configured but boto3 is not installed") from exc

        client = boto3.client(
            "s3",
            endpoint_url=self.config.endpoint,
            aws_access_key_id=self.config.access_key,
            aws_secret_access_key=self.config.secret_key,
            region_name=self.config.region,
        )
        response = client.get_object(Bucket=bucket, Key=key)
        response_body = response["Body"]
        content_length = int(response.get("ContentLength") or 0)
        if max_bytes is not None and content_length > max_bytes:
            response_body.close()
            raise ValueError(f"object exceeds max bytes {max_bytes}: s3://{bucket}/{key}")
        try:
            body = response_body.read() if max_bytes is None else response_body.read(max_bytes + 1)
        finally:
            response_body.close()
        if not isinstance(body, bytes):
            raise RuntimeError(f"S3 object body is not bytes: s3://{bucket}/{key}")
        if max_bytes is not None and len(body) > max_bytes:
            raise ValueError(f"object exceeds max bytes {max_bytes}: s3://{bucket}/{key}")
        return body

    @staticmethod
    def _normalize_key(key: str) -> str:
        cleaned = key.strip().replace("\\", "/")
        parts = [part for part in cleaned.split("/") if part not in {"", ".", ".."}]
        if not parts:
            raise ValueError("object storage key must not be empty")
        return "/".join(parts)
