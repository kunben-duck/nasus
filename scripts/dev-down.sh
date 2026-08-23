#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/dev-runtime-env.sh"

PID_DIR="$NASUS_DEV_RUNTIME_DIR/pids"

terminate_tree() {
  pid="$1"
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    terminate_tree "$child"
  done
  kill "$pid" >/dev/null 2>&1 || true
}

for component in portal api workflow runner; do
  pid_file="$PID_DIR/$component.pid"
  if [[ ! -f "$pid_file" ]]; then
    continue
  fi
  pid="$(<"$pid_file")"
  if kill -0 "$pid" >/dev/null 2>&1; then
    terminate_tree "$pid"
    for _attempt in $(seq 1 20); do
      if ! kill -0 "$pid" >/dev/null 2>&1; then
        break
      fi
      sleep 0.1
    done
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi
  rm -f "$pid_file"
done

if [[ "${1:-}" == "--infra" ]]; then
  docker compose --profile app --profile temporal stop temporal-ui temporal minio postgres
fi

echo "Nasus host application processes stopped."
