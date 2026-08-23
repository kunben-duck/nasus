#!/usr/bin/env python3
"""Create and restore logical, version-aware S3/MinIO snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import boto3
from botocore.exceptions import ClientError


SNAPSHOT_SCHEMA = "nasus.object-storage-snapshot/v1"
CHUNK_SIZE = 1024 * 1024


def _required(name: str, *fallbacks: str) -> str:
    for candidate in (name, *fallbacks):
        value = os.getenv(candidate, "").strip()
        if value:
            return value
    raise SystemExit(f"Required environment variable is missing: {name}")


def _client():
    endpoint = _required("NASUS_S3_ENDPOINT")
    access_key = _required("NASUS_S3_ACCESS_KEY", "MINIO_ROOT_USER")
    secret_key = _required("NASUS_S3_SECRET_KEY", "MINIO_ROOT_PASSWORD")
    region = os.getenv("NASUS_S3_REGION", "us-east-1")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )


def _bucket() -> str:
    return _required("NASUS_S3_BUCKET")


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    raise TypeError(f"Unsupported JSON value: {type(value)!r}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _object_path(root: Path, key: str, version_id: str) -> Path:
    opaque_name = hashlib.sha256(f"{key}\0{version_id}".encode("utf-8")).hexdigest()
    return root / "objects" / opaque_name[:2] / f"{opaque_name}.blob"


def _iter_versions(client, bucket: str) -> Iterable[dict[str, Any]]:
    paginator = client.get_paginator("list_object_versions")
    sequence = 0
    for page in paginator.paginate(Bucket=bucket):
        page_events: list[tuple[str, dict[str, Any]]] = []
        page_events.extend(("version", item) for item in page.get("Versions", []))
        page_events.extend(("delete_marker", item) for item in page.get("DeleteMarkers", []))
        page_events.sort(
            key=lambda pair: (
                pair[1]["Key"],
                -pair[1]["LastModified"].timestamp(),
                pair[0],
            )
        )
        for event_type, item in page_events:
            yield {
                "event_type": event_type,
                "key": item["Key"],
                "version_id": item["VersionId"],
                "is_latest": bool(item.get("IsLatest")),
                "last_modified": item["LastModified"],
                "etag": str(item.get("ETag", "")).strip('"'),
                "size": int(item.get("Size", 0)),
                "list_order": sequence,
            }
            sequence += 1


def _response_properties(response: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    mappings = {
        "ContentType": "content_type",
        "CacheControl": "cache_control",
        "ContentDisposition": "content_disposition",
        "ContentEncoding": "content_encoding",
        "ContentLanguage": "content_language",
        "WebsiteRedirectLocation": "website_redirect_location",
    }
    for source, target in mappings.items():
        value = response.get(source)
        if value:
            properties[target] = value
    metadata = response.get("Metadata") or {}
    if metadata:
        properties["metadata"] = dict(metadata)
    return properties


def backup(output: Path) -> None:
    client = _client()
    bucket = _bucket()
    output.mkdir(parents=True, exist_ok=False)
    (output / "objects").mkdir()

    versioning = client.get_bucket_versioning(Bucket=bucket).get("Status", "Disabled")
    events: list[dict[str, Any]] = []
    total_bytes = 0
    for event in _iter_versions(client, bucket):
        if event["event_type"] == "version":
            payload_path = _object_path(output, event["key"], event["version_id"])
            payload_path.parent.mkdir(parents=True, exist_ok=True)
            response = client.get_object(
                Bucket=bucket,
                Key=event["key"],
                VersionId=event["version_id"],
            )
            digest = hashlib.sha256()
            with payload_path.open("wb") as handle:
                body = response["Body"]
                try:
                    while True:
                        chunk = body.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        handle.write(chunk)
                        digest.update(chunk)
                finally:
                    body.close()
            event["payload_path"] = str(payload_path.relative_to(output))
            event["sha256"] = digest.hexdigest()
            event["properties"] = _response_properties(response)
            total_bytes += payload_path.stat().st_size
        events.append(event)

    snapshot = {
        "schema": SNAPSHOT_SCHEMA,
        "created_at": datetime.now(timezone.utc),
        "bucket": bucket,
        "versioning_status": versioning,
        "event_count": len(events),
        "object_version_count": sum(item["event_type"] == "version" for item in events),
        "delete_marker_count": sum(item["event_type"] == "delete_marker" for item in events),
        "payload_bytes": total_bytes,
        "events": events,
    }
    snapshot_path = output / "object-storage.json"
    snapshot_path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "bucket": bucket,
                "events": len(events),
                "payload_bytes": total_bytes,
                "snapshot": str(snapshot_path),
            },
            sort_keys=True,
        )
    )


def _load_snapshot(snapshot_dir: Path) -> dict[str, Any]:
    path = snapshot_dir / "object-storage.json"
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Invalid object-storage snapshot {path}: {exc}") from exc
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise SystemExit(f"Unsupported object-storage snapshot schema: {snapshot.get('schema')!r}")
    return snapshot


def validate(snapshot_dir: Path) -> dict[str, Any]:
    snapshot = _load_snapshot(snapshot_dir)
    failures: list[str] = []
    for event in snapshot["events"]:
        if event["event_type"] != "version":
            continue
        payload_path = snapshot_dir / event["payload_path"]
        if not payload_path.is_file():
            failures.append(f"missing payload: {event['payload_path']}")
            continue
        digest = _sha256_file(payload_path)
        if digest != event["sha256"]:
            failures.append(f"checksum mismatch: {event['payload_path']}")
    if failures:
        raise SystemExit("Object-storage snapshot validation failed:\n- " + "\n- ".join(failures))
    return snapshot


def _clear_bucket(client, bucket: str) -> None:
    pending: list[dict[str, str]] = []
    for event in _iter_versions(client, bucket):
        pending.append({"Key": event["key"], "VersionId": event["version_id"]})
        if len(pending) == 1000:
            client.delete_objects(Bucket=bucket, Delete={"Objects": pending, "Quiet": True})
            pending = []
    if pending:
        client.delete_objects(Bucket=bucket, Delete={"Objects": pending, "Quiet": True})


def _put_arguments(event: dict[str, Any], body) -> dict[str, Any]:
    properties = event.get("properties") or {}
    arguments: dict[str, Any] = {"Body": body}
    mappings = {
        "content_type": "ContentType",
        "cache_control": "CacheControl",
        "content_disposition": "ContentDisposition",
        "content_encoding": "ContentEncoding",
        "content_language": "ContentLanguage",
        "website_redirect_location": "WebsiteRedirectLocation",
        "metadata": "Metadata",
    }
    for source, target in mappings.items():
        value = properties.get(source)
        if value:
            arguments[target] = value
    return arguments


def restore(snapshot_dir: Path, *, clear: bool) -> None:
    if not clear:
        raise SystemExit("Restore requires --clear to avoid mixing snapshot and target facts")
    snapshot = validate(snapshot_dir)
    client = _client()
    bucket = _bucket()
    if bucket != snapshot["bucket"] and os.getenv("NASUS_RESTORE_ALLOW_BUCKET_REMAP") != "true":
        raise SystemExit(
            f"Snapshot bucket {snapshot['bucket']!r} does not match target {bucket!r}; "
            "set NASUS_RESTORE_ALLOW_BUCKET_REMAP=true for an intentional remap"
        )
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)
    client.put_bucket_versioning(
        Bucket=bucket,
        VersioningConfiguration={"Status": "Enabled"},
    )
    _clear_bucket(client, bucket)

    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in snapshot["events"]:
        by_key[event["key"]].append(event)
    for key in sorted(by_key):
        # S3 returns each key newest-first. Replay in reverse to reconstruct history.
        for event in sorted(by_key[key], key=lambda item: item["list_order"], reverse=True):
            if event["event_type"] == "delete_marker":
                client.delete_object(Bucket=bucket, Key=key)
                continue
            payload_path = snapshot_dir / event["payload_path"]
            with payload_path.open("rb") as body:
                client.put_object(Bucket=bucket, Key=key, **_put_arguments(event, body))

    verify_live(snapshot_dir)
    print(json.dumps({"bucket": bucket, "restored_events": len(snapshot["events"])}, sort_keys=True))


def _latest_by_key(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in snapshot["events"]:
        if event.get("is_latest"):
            latest[event["key"]] = event
    return latest


def _live_event_counts(client, bucket: str) -> dict[str, int]:
    counts = {"version": 0, "delete_marker": 0}
    for event in _iter_versions(client, bucket):
        counts[event["event_type"]] += 1
    return counts


def verify_live(snapshot_dir: Path) -> None:
    snapshot = validate(snapshot_dir)
    client = _client()
    bucket = _bucket()
    failures: list[str] = []
    for key, event in _latest_by_key(snapshot).items():
        if event["event_type"] == "delete_marker":
            try:
                client.head_object(Bucket=bucket, Key=key)
            except ClientError as exc:
                status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                if status in {404, 405}:
                    continue
                failures.append(f"unexpected error for deleted key {key}: {exc}")
            else:
                failures.append(f"deleted key is live: {key}")
            continue
        response = client.get_object(Bucket=bucket, Key=key)
        digest = hashlib.sha256()
        body = response["Body"]
        try:
            while True:
                chunk = body.read(CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
        finally:
            body.close()
        if digest.hexdigest() != event["sha256"]:
            failures.append(f"live payload mismatch: {key}")

    counts = _live_event_counts(client, bucket)
    expected_versions = int(snapshot["object_version_count"])
    expected_deletes = int(snapshot["delete_marker_count"])
    if counts["version"] != expected_versions:
        failures.append(
            f"version count mismatch: expected {expected_versions}, got {counts['version']}"
        )
    if counts["delete_marker"] != expected_deletes:
        failures.append(
            f"delete marker count mismatch: expected {expected_deletes}, got {counts['delete_marker']}"
        )
    if failures:
        raise SystemExit("Live object-storage verification failed:\n- " + "\n- ".join(failures))
    print(
        json.dumps(
            {
                "bucket": bucket,
                "verified_versions": counts["version"],
                "verified_delete_markers": counts["delete_marker"],
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--output", type=Path, required=True)
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--input", type=Path, required=True)
    restore_parser.add_argument("--clear", action="store_true")
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--input", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify-live")
    verify_parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "backup":
        backup(args.output)
    elif args.command == "restore":
        restore(args.input, clear=args.clear)
    elif args.command == "validate":
        snapshot = validate(args.input)
        print(json.dumps({"valid": True, "events": len(snapshot["events"])}, sort_keys=True))
    elif args.command == "verify-live":
        verify_live(args.input)


if __name__ == "__main__":
    try:
        main()
    except ClientError as exc:
        print(f"S3 operation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
