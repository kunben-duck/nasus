#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/dev-runtime-env.sh"

PID_DIR="$NASUS_DEV_RUNTIME_DIR/pids"
LOG_DIR="$NASUS_DEV_RUNTIME_DIR/logs"
FOREGROUND="${NASUS_DEV_FOREGROUND:-false}"
mkdir -p "$PID_DIR" "$LOG_DIR"

cleanup_on_error() {
  "$ROOT_DIR/scripts/dev-down.sh" >/dev/null 2>&1 || true
}
trap cleanup_on_error ERR

port_is_listening() {
  lsof -tiTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

assert_port_available() {
  component="$1"
  port="$2"
  pid_file="$PID_DIR/$component.pid"
  if [[ -f "$pid_file" ]] && kill -0 "$(<"$pid_file")" >/dev/null 2>&1; then
    echo "$component is already managed by Nasus dev runtime (pid $(<"$pid_file"))." >&2
    exit 1
  fi
  rm -f "$pid_file"
  if port_is_listening "$port"; then
    echo "Port $port for $component is already in use. Stop the existing process before running dev:up." >&2
    exit 1
  fi
}

wait_for_http() {
  name="$1"
  url="$2"
  pid="$3"
  log_file="$4"
  for _attempt in $(seq 1 120); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      echo "$name exited during startup." >&2
      tail -n 100 "$log_file" >&2 || true
      return 1
    fi
    sleep 0.25
  done
  echo "$name did not become ready at $url." >&2
  tail -n 100 "$log_file" >&2 || true
  return 1
}

wait_for_temporal_namespace() {
  "$ROOT_DIR/.venv/bin/python" - <<'PY'
from __future__ import annotations

import asyncio
import os
import time

from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
from temporalio.client import Client


async def wait_until_ready() -> None:
    address = os.environ["NASUS_TEMPORAL_ADDRESS"]
    namespace = os.environ["NASUS_TEMPORAL_NAMESPACE"]
    deadline = time.monotonic() + 120
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            client = await Client.connect(address, namespace=namespace)
            response = await client.service_client.workflow_service.describe_namespace(
                DescribeNamespaceRequest(namespace=namespace)
            )
            if response.namespace_info.name == namespace:
                return
        except Exception as exc:
            last_error = exc
        await asyncio.sleep(0.5)
    raise RuntimeError(
        f"Temporal namespace {namespace!r} did not become ready at "
        f"{address}: {last_error}"
    )


asyncio.run(wait_until_ready())
PY
}

start_process() {
  name="$1"
  shift
  log_file="$LOG_DIR/$name.log"
  (
    cd "$ROOT_DIR"
    exec nohup "$@" </dev/null
  ) >"$log_file" 2>&1 &
  pid=$!
  echo "$pid" >"$PID_DIR/$name.pid"
  echo "$pid"
}

assert_port_available runner "$NASUS_RUNNER_PORT"
assert_port_available api "$NASUS_API_PORT"
assert_port_available portal "$NASUS_PORTAL_PORT"

echo "==> Starting Docker infrastructure: PostgreSQL, MinIO, Temporal"
docker compose --profile app --profile temporal up -d postgres minio minio-init temporal temporal-ui

echo "==> Waiting for PostgreSQL"
for _attempt in $(seq 1 60); do
  if docker compose exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
docker compose exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null

echo "==> Waiting for Temporal namespace $NASUS_TEMPORAL_NAMESPACE"
wait_for_temporal_namespace

echo "==> Applying Alembic migrations"
"$ROOT_DIR/.venv/bin/alembic" -c "$ROOT_DIR/apps/api/alembic.ini" upgrade head

echo "==> Starting Playwright runner on $NASUS_RUNNER_PORT"
runner_pid="$(start_process runner npm --prefix apps/runner start)"
wait_for_http runner "$NASUS_RUNNER_ENDPOINT/readyz" "$runner_pid" "$LOG_DIR/runner.log"

echo "==> Starting Temporal Agent workflow worker"
worker_pid="$(start_process workflow ./.venv/bin/python -m apps.api.app.infrastructure.workflow.agent_goal_workflow_worker)"
sleep 1
if ! kill -0 "$worker_pid" >/dev/null 2>&1; then
  echo "Temporal Agent workflow worker exited during startup." >&2
  tail -n 100 "$LOG_DIR/workflow.log" >&2 || true
  exit 1
fi

echo "==> Starting API on $NASUS_API_PORT"
api_pid="$(start_process api ./.venv/bin/python -m uvicorn apps.api.app.main:app --app-dir . --host 0.0.0.0 --port "$NASUS_API_PORT")"
wait_for_http api "http://127.0.0.1:${NASUS_API_PORT}/readyz" "$api_pid" "$LOG_DIR/api.log"

echo "==> Starting Portal on $NASUS_PORTAL_PORT"
portal_pid="$(start_process portal npm --prefix apps/portal run dev -- --host 0.0.0.0 --port "$NASUS_PORTAL_PORT")"
wait_for_http portal "http://127.0.0.1:${NASUS_PORTAL_PORT}/build" "$portal_pid" "$LOG_DIR/portal.log"

trap - ERR
echo "Nasus durable development runtime is ready."
echo "Portal: http://127.0.0.1:${NASUS_PORTAL_PORT}/build"
echo "API: http://127.0.0.1:${NASUS_API_PORT}/readyz"
echo "Temporal UI: http://127.0.0.1:${TEMPORAL_UI_PORT}"
echo "Logs: $LOG_DIR"

if [[ "$FOREGROUND" == "true" ]]; then
  cleanup_foreground() {
    "$ROOT_DIR/scripts/dev-down.sh" >/dev/null 2>&1 || true
  }

  trap cleanup_foreground EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  echo "Supervising host application processes. Press Ctrl+C to stop them."
  while true; do
    for component in runner workflow api portal; do
      pid_file="$PID_DIR/$component.pid"
      if [[ ! -f "$pid_file" ]] || ! kill -0 "$(<"$pid_file")" >/dev/null 2>&1; then
        echo "$component exited while the development runtime was active." >&2
        tail -n 100 "$LOG_DIR/$component.log" >&2 || true
        exit 1
      fi
    done
    sleep 1
  done
fi
