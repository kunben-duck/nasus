#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ID="${NASUS_BACKUP_VERIFY_RUN_ID:-$(date +%s)-$$}"
PROJECT="${NASUS_BACKUP_VERIFY_COMPOSE_PROJECT:-nasus_backup_verify_${RUN_ID//[^a-zA-Z0-9]/_}}"
POSTGRES_PORT="${NASUS_BACKUP_VERIFY_POSTGRES_PORT:-56$(( (10#$$ % 80) + 100 ))}"
MINIO_API_PORT="${NASUS_BACKUP_VERIFY_MINIO_API_PORT:-57$(( (10#$$ % 80) + 100 ))}"
MINIO_CONSOLE_PORT="${NASUS_BACKUP_VERIFY_MINIO_CONSOLE_PORT:-58$(( (10#$$ % 80) + 100 ))}"
BACKUP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/nasus-backup-verify.XXXXXX")"
BACKUP_ID="backup-restore-verification"
export COMPOSE_PROJECT_NAME="$PROJECT"
export POSTGRES_DB="nasus"
export POSTGRES_USER="nasus"
export POSTGRES_PASSWORD="nasus_backup_verify_password"
export POSTGRES_PORT MINIO_API_PORT MINIO_CONSOLE_PORT
export MINIO_ROOT_USER="nasus"
export MINIO_ROOT_PASSWORD="nasus_backup_verify_password"
export NASUS_S3_ENDPOINT="http://127.0.0.1:$MINIO_API_PORT"
export NASUS_S3_BUCKET="nasus-backup-verify"
export NASUS_S3_ACCESS_KEY="$MINIO_ROOT_USER"
export NASUS_S3_SECRET_KEY="$MINIO_ROOT_PASSWORD"
export NASUS_BACKUP_ROOT="$BACKUP_ROOT"
export NASUS_BACKUP_ID="$BACKUP_ID"
export NASUS_BACKUP_POSTGRES_DATABASES="nasus"
export NASUS_BACKUP_MANIFEST_HMAC_KEY="nasus-backup-verification-hmac-key-32-bytes"

cleanup() {
  docker compose down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$BACKUP_ROOT"
}
trap cleanup EXIT

cd "$ROOT_DIR"
echo "==> Starting isolated PostgreSQL and MinIO"
docker compose up -d postgres minio minio-init
for _attempt in $(seq 1 60); do
  postgres_container_id="$(
    docker compose ps --all --quiet postgres 2>/dev/null || true
  )"
  if [[ -z "$postgres_container_id" ]]; then
    sleep 0.25
    continue
  fi
  postgres_health="$(
    docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' \
      "$postgres_container_id" 2>/dev/null || true
  )"
  if [[ "$postgres_health" == "healthy" ]]; then
    break
  fi
  sleep 0.25
done
if [[ "${postgres_health:-}" != "healthy" ]]; then
  echo "PostgreSQL did not reach Docker healthy state." >&2
  docker compose logs postgres >&2
  exit 1
fi
docker compose exec -T postgres pg_isready \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null
minio_init_status=""
minio_init_exit_code=""
for _attempt in $(seq 1 60); do
  minio_init_container_id="$(
    docker compose ps --all --quiet minio-init 2>/dev/null || true
  )"
  if [[ -z "$minio_init_container_id" ]]; then
    sleep 0.25
    continue
  fi
  minio_init_status="$(
    docker inspect --format '{{.State.Status}}' "$minio_init_container_id"
  )"
  minio_init_exit_code="$(
    docker inspect --format '{{.State.ExitCode}}' "$minio_init_container_id"
  )"
  if [[ "$minio_init_status" == "exited" ]]; then
    break
  fi
  sleep 0.25
done
if [[ "$minio_init_status" != "exited" || "$minio_init_exit_code" != "0" ]]; then
  echo "MinIO initialization did not complete successfully." >&2
  docker compose logs minio minio-init >&2
  exit 1
fi

echo "==> Seeding database and versioned object history"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE backup_restore_probe (
  id text PRIMARY KEY,
  value text NOT NULL
);
INSERT INTO backup_restore_probe (id, value) VALUES ('seed', 'before-backup');
SQL
"$ROOT_DIR/.venv/bin/python" - <<'PY'
import os
import boto3

client = boto3.client(
    "s3",
    endpoint_url=os.environ["NASUS_S3_ENDPOINT"],
    aws_access_key_id=os.environ["NASUS_S3_ACCESS_KEY"],
    aws_secret_access_key=os.environ["NASUS_S3_SECRET_KEY"],
    region_name="us-east-1",
)
bucket = os.environ["NASUS_S3_BUCKET"]
client.put_object(Bucket=bucket, Key="evidence/run.json", Body=b"version-one")
client.put_object(Bucket=bucket, Key="evidence/run.json", Body=b"version-two")
client.put_object(Bucket=bucket, Key="evidence/deleted.json", Body=b"deleted-evidence")
client.delete_object(Bucket=bucket, Key="evidence/deleted.json")
PY

echo "==> Creating logical backup"
"$ROOT_DIR/scripts/backup-data.sh"
BACKUP_DIR="$BACKUP_ROOT/$BACKUP_ID"

echo "==> Mutating both stores after the recovery point"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 <<'SQL'
UPDATE backup_restore_probe SET value = 'after-backup' WHERE id = 'seed';
INSERT INTO backup_restore_probe (id, value) VALUES ('later', 'must-disappear');
SQL
"$ROOT_DIR/.venv/bin/python" - <<'PY'
import os
import boto3

client = boto3.client(
    "s3",
    endpoint_url=os.environ["NASUS_S3_ENDPOINT"],
    aws_access_key_id=os.environ["NASUS_S3_ACCESS_KEY"],
    aws_secret_access_key=os.environ["NASUS_S3_SECRET_KEY"],
    region_name="us-east-1",
)
bucket = os.environ["NASUS_S3_BUCKET"]
client.put_object(Bucket=bucket, Key="evidence/run.json", Body=b"version-three")
client.put_object(Bucket=bucket, Key="evidence/extra.json", Body=b"must-disappear")
PY

echo "==> Restoring the recovery point"
NASUS_RESTORE_CONFIRM="restore:$BACKUP_ID" \
NASUS_RESTORE_QUIESCED=true \
NASUS_RESTORE_CLEAR_OBJECT_STORAGE=true \
  "$ROOT_DIR/scripts/restore-data.sh" "$BACKUP_DIR"

echo "==> Verifying exact PostgreSQL and MinIO recovery"
database_state="$(docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
  "SELECT string_agg(id || '=' || value, ',' ORDER BY id) FROM backup_restore_probe")"
if [[ "$database_state" != "seed=before-backup" ]]; then
  echo "Unexpected restored database state: $database_state" >&2
  exit 1
fi
"$ROOT_DIR/.venv/bin/python" - <<'PY'
import os
import boto3
from botocore.exceptions import ClientError

client = boto3.client(
    "s3",
    endpoint_url=os.environ["NASUS_S3_ENDPOINT"],
    aws_access_key_id=os.environ["NASUS_S3_ACCESS_KEY"],
    aws_secret_access_key=os.environ["NASUS_S3_SECRET_KEY"],
    region_name="us-east-1",
)
bucket = os.environ["NASUS_S3_BUCKET"]
assert client.get_object(Bucket=bucket, Key="evidence/run.json")["Body"].read() == b"version-two"
for key in ("evidence/deleted.json", "evidence/extra.json"):
    try:
        client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        assert exc.response["ResponseMetadata"]["HTTPStatusCode"] in {404, 405}
    else:
        raise AssertionError(f"unexpected live object after restore: {key}")
PY

echo "Backup/restore verification passed."
