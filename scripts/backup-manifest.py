#!/usr/bin/env python3
"""Create and verify integrity manifests for Nasus logical backups."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MANIFEST_SCHEMA = "nasus.backup-manifest/v1"
MANIFEST_NAME = "backup-manifest.json"
CHUNK_SIZE = 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_payload(manifest: dict[str, Any]) -> bytes:
    unsigned = dict(manifest)
    unsigned.pop("integrity", None)
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hmac_key(required: bool = False) -> str:
    key = os.getenv("NASUS_BACKUP_MANIFEST_HMAC_KEY", "")
    if required and len(key) < 32:
        raise SystemExit("NASUS_BACKUP_MANIFEST_HMAC_KEY must contain at least 32 characters")
    return key


def create(root: Path, backup_id: str, databases: list[str]) -> None:
    environment = os.getenv("NASUS_ENV", "local").lower()
    key = _hmac_key(required=environment in {"staging", "production"})
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == MANIFEST_NAME:
            continue
        files.append(
            {
                "path": str(path.relative_to(root)),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "backup_id": backup_id,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment": environment,
        "postgres_databases": databases,
        "object_storage_bucket": os.getenv("NASUS_S3_BUCKET", "nasus-artifacts"),
        "file_count": len(files),
        "total_bytes": sum(item["size"] for item in files),
        "files": files,
    }
    if key:
        signature = hmac.new(key.encode("utf-8"), _canonical_payload(manifest), hashlib.sha256)
        manifest["integrity"] = {"algorithm": "hmac-sha256", "signature": signature.hexdigest()}
    else:
        manifest["integrity"] = {"algorithm": "sha256-files", "signature": None}
    (root / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"backup_id": backup_id, "files": len(files)}, sort_keys=True))


def load_and_verify(root: Path) -> dict[str, Any]:
    path = root / MANIFEST_NAME
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Invalid backup manifest {path}: {exc}") from exc
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise SystemExit(f"Unsupported backup manifest schema: {manifest.get('schema')!r}")

    failures: list[str] = []
    expected_paths = set()
    for item in manifest.get("files", []):
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            failures.append(f"unsafe path: {relative}")
            continue
        expected_paths.add(str(relative))
        file_path = root / relative
        if not file_path.is_file():
            failures.append(f"missing file: {relative}")
            continue
        if file_path.stat().st_size != item["size"]:
            failures.append(f"size mismatch: {relative}")
            continue
        if _sha256(file_path) != item["sha256"]:
            failures.append(f"checksum mismatch: {relative}")

    actual_paths = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path.name != MANIFEST_NAME
    }
    extras = sorted(actual_paths - expected_paths)
    if extras:
        failures.extend(f"untracked file: {path}" for path in extras)

    integrity = manifest.get("integrity") or {}
    if integrity.get("algorithm") == "hmac-sha256":
        key = _hmac_key(required=True)
        expected = hmac.new(
            key.encode("utf-8"), _canonical_payload(manifest), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, str(integrity.get("signature", ""))):
            failures.append("manifest HMAC mismatch")
    elif manifest.get("environment") in {"staging", "production"}:
        failures.append("production backup is not HMAC signed")

    if failures:
        raise SystemExit("Backup manifest validation failed:\n- " + "\n- ".join(failures))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--root", type=Path, required=True)
    create_parser.add_argument("--backup-id", required=True)
    create_parser.add_argument("--database", action="append", default=[])
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--root", type=Path, required=True)
    id_parser = subparsers.add_parser("backup-id")
    id_parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "create":
        create(args.root, args.backup_id, args.database)
    else:
        manifest = load_and_verify(args.root)
        if args.command == "verify":
            print(
                json.dumps(
                    {
                        "valid": True,
                        "backup_id": manifest["backup_id"],
                        "files": manifest["file_count"],
                    },
                    sort_keys=True,
                )
            )
        else:
            print(manifest["backup_id"])


if __name__ == "__main__":
    main()
