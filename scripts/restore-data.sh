#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${1:-}"
POSTGRES_USER="${POSTGRES_USER:-nasus}"
NASUS_S3_ENDPOINT="${NASUS_S3_ENDPOINT:-http://127.0.0.1:${MINIO_API_PORT:-9000}}"
NASUS_S3_BUCKET="${NASUS_S3_BUCKET:-nasus-artifacts}"
NASUS_S3_ACCESS_KEY="${NASUS_S3_ACCESS_KEY:-${MINIO_ROOT_USER:-nasus}}"
NASUS_S3_SECRET_KEY="${NASUS_S3_SECRET_KEY:-${MINIO_ROOT_PASSWORD:-nasus_dev_password}}"
export NASUS_S3_ENDPOINT NASUS_S3_BUCKET NASUS_S3_ACCESS_KEY NASUS_S3_SECRET_KEY

if [[ -z "$BACKUP_DIR" ]]; then
  echo "Usage: NASUS_RESTORE_CONFIRM=restore:<backup-id> $0 <backup-directory>" >&2
  exit 2
fi
BACKUP_DIR="$(cd "$BACKUP_DIR" && pwd)"
PYTHON_BIN="${NASUS_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

echo "==> Validating backup manifest and object payloads"
"$PYTHON_BIN" "$ROOT_DIR/scripts/backup-manifest.py" verify --root "$BACKUP_DIR"
"$PYTHON_BIN" "$ROOT_DIR/scripts/object-storage-snapshot.py" \
  validate --input "$BACKUP_DIR/object-storage"
BACKUP_ID="$("$PYTHON_BIN" "$ROOT_DIR/scripts/backup-manifest.py" backup-id --root "$BACKUP_DIR")"
if [[ "${NASUS_RESTORE_CONFIRM:-}" != "restore:$BACKUP_ID" ]]; then
  echo "Restore is destructive. Set NASUS_RESTORE_CONFIRM=restore:$BACKUP_ID to continue." >&2
  exit 1
fi
if [[ "${NASUS_RESTORE_QUIESCED:-false}" != "true" ]]; then
  echo "Restore requires NASUS_RESTORE_QUIESCED=true after API, workers, and Temporal are stopped." >&2
  exit 1
fi
if [[ "${NASUS_RESTORE_CLEAR_OBJECT_STORAGE:-false}" != "true" ]]; then
  echo "Restore requires NASUS_RESTORE_CLEAR_OBJECT_STORAGE=true to authorize exact bucket replacement." >&2
  exit 1
fi

mapfile_compat() {
  while IFS= read -r line; do
    [[ -n "$line" ]] && databases+=("$line")
  done
}
databases=()
mapfile_compat < <(
  "$PYTHON_BIN" -c \
    'import json,sys; print("\n".join(json.load(open(sys.argv[1]))["postgres_databases"]))' \
    "$BACKUP_DIR/backup-manifest.json"
)

echo "==> Restoring PostgreSQL databases: ${databases[*]}"
for database in "${databases[@]}"; do
  if [[ ! "$database" =~ ^[a-zA-Z0-9_]+$ ]]; then
    echo "Unsafe PostgreSQL database name in manifest: $database" >&2
    exit 1
  fi
  dump_path="$BACKUP_DIR/postgres/$database.dump"
  docker compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$database' AND pid <> pg_backend_pid();" >/dev/null
  if ! docker compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres -Atc \
    "SELECT 1 FROM pg_database WHERE datname = '$database'" | grep -qx 1; then
    docker compose exec -T postgres createdb -U "$POSTGRES_USER" "$database"
  fi
  docker compose exec -T postgres pg_restore \
    -U "$POSTGRES_USER" \
    --dbname "$database" \
    --clean \
    --if-exists \
    --exit-on-error \
    --no-owner \
    --no-acl <"$dump_path"
done

echo "==> Restoring MinIO/S3 version history"
"$PYTHON_BIN" "$ROOT_DIR/scripts/object-storage-snapshot.py" \
  restore --input "$BACKUP_DIR/object-storage" --clear

REPORT_DIR="${NASUS_RESTORE_REPORT_ROOT:-$ROOT_DIR/.nasus/restore-reports}"
mkdir -p "$REPORT_DIR"
chmod 700 "$REPORT_DIR"
REPORT_PATH="$REPORT_DIR/${BACKUP_ID}-$(date -u +%Y%m%dT%H%M%SZ).json"
printf '{"backup_id":"%s","restored_at":"%s","status":"verified"}\n' \
  "$BACKUP_ID" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$REPORT_PATH"
chmod 600 "$REPORT_PATH"
echo "Restore completed and verified: $REPORT_PATH"
