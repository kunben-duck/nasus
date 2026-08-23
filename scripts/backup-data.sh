#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_ROOT="${NASUS_BACKUP_ROOT:-$ROOT_DIR/.nasus/backups}"
BACKUP_ID="${NASUS_BACKUP_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
FINAL_DIR="$BACKUP_ROOT/$BACKUP_ID"
WORK_DIR="$BACKUP_ROOT/.${BACKUP_ID}.partial"
POSTGRES_USER="${POSTGRES_USER:-nasus}"
POSTGRES_DB="${POSTGRES_DB:-nasus}"
NASUS_S3_ENDPOINT="${NASUS_S3_ENDPOINT:-http://127.0.0.1:${MINIO_API_PORT:-9000}}"
NASUS_S3_BUCKET="${NASUS_S3_BUCKET:-nasus-artifacts}"
NASUS_S3_ACCESS_KEY="${NASUS_S3_ACCESS_KEY:-${MINIO_ROOT_USER:-nasus}}"
NASUS_S3_SECRET_KEY="${NASUS_S3_SECRET_KEY:-${MINIO_ROOT_PASSWORD:-nasus_dev_password}}"
export NASUS_S3_ENDPOINT NASUS_S3_BUCKET NASUS_S3_ACCESS_KEY NASUS_S3_SECRET_KEY

if [[ "${NASUS_LOAD_DOTENV:-false}" == "true" && -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

if [[ "${NASUS_ENV:-local}" =~ ^(staging|production)$ ]] && [[ "${NASUS_BACKUP_QUIESCED:-false}" != "true" ]]; then
  echo "Production backup requires NASUS_BACKUP_QUIESCED=true after write traffic is drained." >&2
  exit 1
fi
if [[ -e "$FINAL_DIR" || -e "$WORK_DIR" ]]; then
  echo "Backup destination already exists: $FINAL_DIR" >&2
  exit 1
fi

PYTHON_BIN="${NASUS_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi
mkdir -p "$BACKUP_ROOT"
chmod 700 "$BACKUP_ROOT"
mkdir -m 700 "$WORK_DIR" "$WORK_DIR/postgres"
cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup ERR INT TERM

database_exists() {
  local database="$1"
  docker compose exec -T postgres psql \
    -U "$POSTGRES_USER" -d postgres -Atc \
    "SELECT 1 FROM pg_database WHERE datname = '$database'" | grep -qx 1
}

database_candidates="${NASUS_BACKUP_POSTGRES_DATABASES:-$POSTGRES_DB,temporal,temporal_visibility}"
IFS=',' read -r -a requested_databases <<<"$database_candidates"
databases=()
for database in "${requested_databases[@]}"; do
  database="${database//[[:space:]]/}"
  [[ -n "$database" ]] || continue
  if [[ ! "$database" =~ ^[a-zA-Z0-9_]+$ ]]; then
    echo "Unsafe PostgreSQL database name: $database" >&2
    exit 1
  fi
  if database_exists "$database"; then
    databases+=("$database")
  elif [[ "$database" == "$POSTGRES_DB" ]]; then
    echo "Required PostgreSQL database does not exist: $database" >&2
    exit 1
  else
    echo "Skipping optional PostgreSQL database that does not exist: $database"
  fi
done
if [[ ${#databases[@]} -eq 0 ]]; then
  echo "No PostgreSQL databases selected for backup." >&2
  exit 1
fi

echo "==> Backing up PostgreSQL databases: ${databases[*]}"
for database in "${databases[@]}"; do
  docker compose exec -T postgres pg_dump \
    -U "$POSTGRES_USER" \
    --dbname "$database" \
    --format custom \
    --compress 6 \
    --no-owner \
    --no-acl >"$WORK_DIR/postgres/$database.dump"
done

echo "==> Backing up all MinIO/S3 object versions"
"$PYTHON_BIN" "$ROOT_DIR/scripts/object-storage-snapshot.py" \
  backup --output "$WORK_DIR/object-storage"

echo "==> Writing integrity manifest"
manifest_args=()
for database in "${databases[@]}"; do
  manifest_args+=(--database "$database")
done
"$PYTHON_BIN" "$ROOT_DIR/scripts/backup-manifest.py" create \
  --root "$WORK_DIR" \
  --backup-id "$BACKUP_ID" \
  "${manifest_args[@]}"
"$PYTHON_BIN" "$ROOT_DIR/scripts/backup-manifest.py" verify --root "$WORK_DIR"
find "$WORK_DIR" -type f -exec chmod 600 {} +
mv "$WORK_DIR" "$FINAL_DIR"
trap - ERR INT TERM

echo "Backup completed: $FINAL_DIR"
echo "Keep this directory on encrypted, access-controlled, immutable storage."
