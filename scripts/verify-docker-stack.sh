#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-nasus_verify}"
POSTGRES_PORT="${POSTGRES_PORT:-55432}"
MINIO_API_PORT="${MINIO_API_PORT:-59000}"
MINIO_CONSOLE_PORT="${MINIO_CONSOLE_PORT:-59001}"
POSTGRES_DB="${POSTGRES_DB:-nasus}"
POSTGRES_USER="${POSTGRES_USER:-nasus}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-nasus_dev_password}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-nasus}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-nasus_dev_password}"
NASUS_S3_BUCKET="${NASUS_S3_BUCKET:-nasus-artifacts}"
NASUS_API_PORT="${NASUS_API_PORT:-18080}"
NASUS_RUNNER_PORT="${NASUS_RUNNER_PORT:-18090}"
NASUS_RUNNER_TARGET_PORT="${NASUS_RUNNER_TARGET_PORT:-18091}"
NASUS_RUNNER_SERVICE_TOKEN="${NASUS_RUNNER_SERVICE_TOKEN:-nasus-verify-runner-service-token-1234567890}"
NASUS_MODEL_PROVIDER_PORT="${NASUS_MODEL_PROVIDER_PORT:-18110}"
NASUS_MODEL_PROVIDER_TOKEN="${NASUS_MODEL_PROVIDER_TOKEN:-nasus-verify-model-provider-token-1234567890}"
NASUS_AUTH_BEARER_TOKEN="${NASUS_AUTH_BEARER_TOKEN:-nasus-verify-api-bearer-token-1234567890}"
NASUS_SETTINGS_ENCRYPTION_SECRET="${NASUS_SETTINGS_ENCRYPTION_SECRET:-nasus-verify-shared-settings-secret-1234567890}"
NASUS_CODE_GRAPH_BINARY="${NASUS_CODE_GRAPH_BINARY:-$ROOT_DIR/.venv/bin/codebase-memory-mcp}"
TEMPORAL_PORT="${TEMPORAL_PORT:-17233}"
NASUS_TEMPORAL_TASK_QUEUE="${NASUS_TEMPORAL_TASK_QUEUE:-nasus-agent-verify}"
KEEP_STACK=true
API_PID=""
API_LOG=""
WORKER_PID=""
WORKER_LOG=""
RUNNER_PID=""
RUNNER_LOG=""
RUNNER_TARGET_PID=""
RUNNER_TARGET_LOG=""
MODEL_PROVIDER_PID=""
MODEL_PROVIDER_LOG=""
VERIFY_OUTPUT_DIR=""

if [[ "${1:-}" == "--down" ]]; then
  KEEP_STACK=false
fi

compose() {
  COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" \
  POSTGRES_PORT="$POSTGRES_PORT" \
  MINIO_API_PORT="$MINIO_API_PORT" \
  MINIO_CONSOLE_PORT="$MINIO_CONSOLE_PORT" \
  POSTGRES_DB="$POSTGRES_DB" \
  POSTGRES_USER="$POSTGRES_USER" \
  POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  MINIO_ROOT_USER="$MINIO_ROOT_USER" \
  MINIO_ROOT_PASSWORD="$MINIO_ROOT_PASSWORD" \
  NASUS_S3_BUCKET="$NASUS_S3_BUCKET" \
  TEMPORAL_PORT="$TEMPORAL_PORT" \
  docker compose --profile app -f "$ROOT_DIR/docker-compose.yml" "$@"
}

stop_api() {
  if [[ -n "$API_PID" ]]; then
    kill "$API_PID" >/dev/null 2>&1 || true
    wait "$API_PID" >/dev/null 2>&1 || true
    API_PID=""
  fi
  for _attempt in {1..20}; do
    if ! curl -fsS "http://127.0.0.1:${NASUS_API_PORT}/healthz" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  local port_pids
  port_pids="$(lsof -tiTCP:"$NASUS_API_PORT" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$port_pids" ]]; then
    kill $port_pids >/dev/null 2>&1 || true
  fi
}

stop_runner_dependencies() {
  local pid
  for pid in "$RUNNER_PID" "$RUNNER_TARGET_PID"; do
    if [[ -n "$pid" ]]; then
      kill "$pid" >/dev/null 2>&1 || true
      wait "$pid" >/dev/null 2>&1 || true
    fi
  done
  RUNNER_PID=""
  RUNNER_TARGET_PID=""
}

stop_model_provider() {
  if [[ -n "$MODEL_PROVIDER_PID" ]]; then
    kill "$MODEL_PROVIDER_PID" >/dev/null 2>&1 || true
    wait "$MODEL_PROVIDER_PID" >/dev/null 2>&1 || true
    MODEL_PROVIDER_PID=""
  fi
}

stop_workflow_worker() {
  if [[ -n "$WORKER_PID" ]]; then
    kill "$WORKER_PID" >/dev/null 2>&1 || true
    wait "$WORKER_PID" >/dev/null 2>&1 || true
    WORKER_PID=""
  fi
}

cleanup() {
  stop_api
  stop_workflow_worker
  stop_runner_dependencies
  stop_model_provider
  if [[ -n "$VERIFY_OUTPUT_DIR" ]]; then
    rm -rf "$VERIFY_OUTPUT_DIR"
  fi
  if [[ -n "$RUNNER_LOG" ]]; then
    rm -f "$RUNNER_LOG"
  fi
  if [[ -n "$RUNNER_TARGET_LOG" ]]; then
    rm -f "$RUNNER_TARGET_LOG"
  fi
  if [[ -n "$WORKER_LOG" ]]; then
    rm -f "$WORKER_LOG"
  fi
  if [[ -n "$MODEL_PROVIDER_LOG" ]]; then
    rm -f "$MODEL_PROVIDER_LOG"
  fi
}

trap cleanup EXIT

wait_for_postgres() {
  local attempt
  for attempt in {1..60}; do
    if compose exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "PostgreSQL did not become ready" >&2
  return 1
}

wait_for_temporal() {
  NASUS_VERIFY_TEMPORAL_ADDRESS="127.0.0.1:${TEMPORAL_PORT}" \
  "$ROOT_DIR/.venv/bin/python" - <<'PY'
from __future__ import annotations

import asyncio
import os
import time

from temporalio.client import Client
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest


async def wait_until_ready() -> None:
    address = os.environ["NASUS_VERIFY_TEMPORAL_ADDRESS"]
    deadline = time.monotonic() + 120
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            client = await Client.connect(address, namespace="default")
            response = await client.service_client.workflow_service.describe_namespace(
                DescribeNamespaceRequest(namespace="default")
            )
            if response.namespace_info.name == "default":
                return
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(1)
    raise RuntimeError(f"Temporal did not become ready at {address}: {last_error}")


asyncio.run(wait_until_ready())
PY
}

wait_for_api() {
  local attempt
  for attempt in {1..60}; do
    if curl -fsS "http://127.0.0.1:${NASUS_API_PORT}/readyz" >/dev/null 2>&1; then
      return 0
    fi
    if [[ -n "$API_PID" ]] && ! kill -0 "$API_PID" >/dev/null 2>&1; then
      echo "Nasus API exited before becoming ready" >&2
      tail -n 80 "$API_LOG" >&2 || true
      return 1
    fi
    sleep 1
  done
  echo "Nasus API did not become ready" >&2
  tail -n 80 "$API_LOG" >&2 || true
  return 1
}

wait_for_http_service() {
  local url="$1"
  local pid="$2"
  local log_file="$3"
  local label="$4"
  local attempt
  for attempt in {1..60}; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      echo "$label exited before becoming ready" >&2
      tail -n 80 "$log_file" >&2 || true
      return 1
    fi
    sleep 0.5
  done
  echo "$label did not become ready" >&2
  tail -n 80 "$log_file" >&2 || true
  return 1
}

start_runner_dependencies() {
  RUNNER_TARGET_LOG="$(mktemp -t nasus-runner-target.XXXXXX.log)"
  (
    cd "$ROOT_DIR/tests/fixtures/system-image"
    exec "$ROOT_DIR/.venv/bin/python" -m http.server "$NASUS_RUNNER_TARGET_PORT" --bind 127.0.0.1
  ) >"$RUNNER_TARGET_LOG" 2>&1 &
  RUNNER_TARGET_PID=$!
  wait_for_http_service \
    "http://127.0.0.1:${NASUS_RUNNER_TARGET_PORT}/" \
    "$RUNNER_TARGET_PID" \
    "$RUNNER_TARGET_LOG" \
    "Runner target fixture"

  RUNNER_LOG="$(mktemp -t nasus-runner-smoke.XXXXXX.log)"
  (
    cd "$ROOT_DIR"
    NASUS_RUNNER_HOST=127.0.0.1 \
    NASUS_RUNNER_PORT="$NASUS_RUNNER_PORT" \
    NASUS_RUNNER_SERVICE_TOKEN="$NASUS_RUNNER_SERVICE_TOKEN" \
    NASUS_RUNNER_ALLOWED_HOSTS=127.0.0.1 \
    NASUS_RUNNER_MAX_CONCURRENCY=1 \
    exec npm --prefix apps/runner start
  ) >"$RUNNER_LOG" 2>&1 &
  RUNNER_PID=$!
  wait_for_http_service \
    "http://127.0.0.1:${NASUS_RUNNER_PORT}/readyz" \
    "$RUNNER_PID" \
    "$RUNNER_LOG" \
    "Nasus Playwright runner"
}

start_model_provider() {
  MODEL_PROVIDER_LOG="$(mktemp -t nasus-model-provider.XXXXXX.log)"
  (
    cd "$ROOT_DIR"
    NASUS_MODEL_FIXTURE_HOST=127.0.0.1 \
    NASUS_MODEL_FIXTURE_PORT="$NASUS_MODEL_PROVIDER_PORT" \
    NASUS_MODEL_FIXTURE_TOKEN="$NASUS_MODEL_PROVIDER_TOKEN" \
    exec "$ROOT_DIR/.venv/bin/python" tests/fixtures/model-provider/openai_compatible_server.py
  ) >"$MODEL_PROVIDER_LOG" 2>&1 &
  MODEL_PROVIDER_PID=$!
  wait_for_http_service \
    "http://127.0.0.1:${NASUS_MODEL_PROVIDER_PORT}/healthz" \
    "$MODEL_PROVIDER_PID" \
    "$MODEL_PROVIDER_LOG" \
    "OpenAI-compatible model protocol fixture"
}

start_workflow_worker() {
  WORKER_LOG="$(mktemp -t nasus-workflow-worker.XXXXXX.log)"
  (
    cd "$ROOT_DIR"
    NASUS_DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT}/${POSTGRES_DB}" \
    NASUS_AUTO_CREATE_TABLES=false \
    NASUS_S3_ENDPOINT="http://127.0.0.1:${MINIO_API_PORT}" \
    NASUS_S3_BUCKET="$NASUS_S3_BUCKET" \
    NASUS_S3_ACCESS_KEY="$MINIO_ROOT_USER" \
    NASUS_S3_SECRET_KEY="$MINIO_ROOT_PASSWORD" \
    NASUS_S3_REGION="us-east-1" \
    NASUS_ENV=production \
    NASUS_AUTH_MODE=required \
    NASUS_AUTH_BEARER_TOKEN="$NASUS_AUTH_BEARER_TOKEN" \
    NASUS_RATE_LIMIT_ENABLED=true \
    NASUS_RATE_LIMIT_BACKEND=postgres \
    NASUS_RATE_LIMIT_WINDOW_SECONDS=60 \
    NASUS_RATE_LIMIT_AUTH_PER_WINDOW=100 \
    NASUS_RATE_LIMIT_AGENT_PER_WINDOW=1000 \
    NASUS_RATE_LIMIT_API_PER_WINDOW=2000 \
    NASUS_CORS_ALLOW_ORIGINS="http://127.0.0.1:5173" \
    NASUS_SETTINGS_ENCRYPTION_SECRET="$NASUS_SETTINGS_ENCRYPTION_SECRET" \
    NASUS_DEFAULT_PROVIDER=openai_compatible \
    NASUS_DEFAULT_BASE_URL="http://127.0.0.1:${NASUS_MODEL_PROVIDER_PORT}/v1" \
    NASUS_DEFAULT_MODEL=nasus-contract-chat \
    NASUS_DEFAULT_API_KEY="$NASUS_MODEL_PROVIDER_TOKEN" \
    NASUS_EMBEDDING_PROVIDER=openai_compatible \
    NASUS_EMBEDDING_BASE_URL="http://127.0.0.1:${NASUS_MODEL_PROVIDER_PORT}/v1" \
    NASUS_EMBEDDING_MODEL=nasus-contract-embedding \
    NASUS_EMBEDDING_API_KEY="$NASUS_MODEL_PROVIDER_TOKEN" \
    NASUS_RERANK_PROVIDER=openai_compatible \
    NASUS_RERANK_BASE_URL="http://127.0.0.1:${NASUS_MODEL_PROVIDER_PORT}/v1" \
    NASUS_RERANK_MODEL=nasus-contract-rerank \
    NASUS_RERANK_API_KEY="$NASUS_MODEL_PROVIDER_TOKEN" \
    NASUS_CODE_GRAPH_MODE=required \
    NASUS_CODE_GRAPH_BINARY="$NASUS_CODE_GRAPH_BINARY" \
    NASUS_AGENT_WORKFLOW_RUNTIME=temporal \
    NASUS_AGENT_GRAPH_RUNTIME=langgraph \
    NASUS_LANGGRAPH_CHECKPOINT_BACKEND=postgres \
    NASUS_LANGGRAPH_AGENT_LOOP_GRAPH=nasus-agent-loop \
    NASUS_TEMPORAL_ADDRESS="127.0.0.1:${TEMPORAL_PORT}" \
    NASUS_TEMPORAL_NAMESPACE=default \
    NASUS_TEMPORAL_TASK_QUEUE="$NASUS_TEMPORAL_TASK_QUEUE" \
    NASUS_TEMPORAL_AGENT_GOAL_WORKFLOW=NasusAgentGoalWorkflow \
    NASUS_TEMPORAL_QUERY_TIMEOUT_SECONDS=120 \
    NASUS_TEMPORAL_QUERY_POLL_INTERVAL_SECONDS=0.1 \
    NASUS_TEMPORAL_MAX_CONCURRENT_ACTIVITIES=1 \
    NASUS_RUNNER_MODE=http \
    NASUS_RUNNER_ENDPOINT="http://127.0.0.1:${NASUS_RUNNER_PORT}" \
    NASUS_RUNNER_SERVICE_TOKEN="$NASUS_RUNNER_SERVICE_TOKEN" \
    NASUS_RUNNER_ALLOWED_HOSTS=127.0.0.1 \
    NASUS_GIT_ALLOWED_HOSTS=github.com \
    NASUS_SOURCE_ALLOWED_LOCAL_ROOTS="$ROOT_DIR/tests/fixtures/system-image" \
    NASUS_SEED_DEMO_DATA=false \
    exec ./.venv/bin/python -m apps.api.app.infrastructure.workflow.agent_goal_workflow_worker
  ) >"$WORKER_LOG" 2>&1 &
  WORKER_PID=$!

  sleep 2
  if ! kill -0 "$WORKER_PID" >/dev/null 2>&1; then
    echo "Nasus Temporal workflow worker exited during startup" >&2
    tail -n 120 "$WORKER_LOG" >&2 || true
    return 1
  fi
}

start_api() {
  if curl -fsS "http://127.0.0.1:${NASUS_API_PORT}/healthz" >/dev/null 2>&1; then
    echo "Port ${NASUS_API_PORT} is already serving /healthz; set NASUS_API_PORT to an unused port." >&2
    return 1
  fi
  API_LOG="$(mktemp -t nasus-api-smoke.XXXXXX.log)"
  (
    cd "$ROOT_DIR"
    NASUS_DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT}/${POSTGRES_DB}" \
    NASUS_AUTO_CREATE_TABLES=false \
    NASUS_S3_ENDPOINT="http://127.0.0.1:${MINIO_API_PORT}" \
    NASUS_S3_BUCKET="$NASUS_S3_BUCKET" \
    NASUS_S3_ACCESS_KEY="$MINIO_ROOT_USER" \
    NASUS_S3_SECRET_KEY="$MINIO_ROOT_PASSWORD" \
    NASUS_S3_REGION="us-east-1" \
    NASUS_ENV=production \
    NASUS_AUTH_MODE=required \
    NASUS_AUTH_BEARER_TOKEN="$NASUS_AUTH_BEARER_TOKEN" \
    NASUS_RATE_LIMIT_ENABLED=true \
    NASUS_RATE_LIMIT_BACKEND=postgres \
    NASUS_RATE_LIMIT_WINDOW_SECONDS=60 \
    NASUS_RATE_LIMIT_AUTH_PER_WINDOW=100 \
    NASUS_RATE_LIMIT_AGENT_PER_WINDOW=1000 \
    NASUS_RATE_LIMIT_API_PER_WINDOW=2000 \
    NASUS_CORS_ALLOW_ORIGINS="http://127.0.0.1:5173" \
    NASUS_SETTINGS_ENCRYPTION_SECRET="$NASUS_SETTINGS_ENCRYPTION_SECRET" \
    NASUS_DEFAULT_PROVIDER=openai_compatible \
    NASUS_DEFAULT_BASE_URL="http://127.0.0.1:${NASUS_MODEL_PROVIDER_PORT}/v1" \
    NASUS_DEFAULT_MODEL=nasus-contract-chat \
    NASUS_DEFAULT_API_KEY="$NASUS_MODEL_PROVIDER_TOKEN" \
    NASUS_EMBEDDING_PROVIDER=openai_compatible \
    NASUS_EMBEDDING_BASE_URL="http://127.0.0.1:${NASUS_MODEL_PROVIDER_PORT}/v1" \
    NASUS_EMBEDDING_MODEL=nasus-contract-embedding \
    NASUS_EMBEDDING_API_KEY="$NASUS_MODEL_PROVIDER_TOKEN" \
    NASUS_RERANK_PROVIDER=openai_compatible \
    NASUS_RERANK_BASE_URL="http://127.0.0.1:${NASUS_MODEL_PROVIDER_PORT}/v1" \
    NASUS_RERANK_MODEL=nasus-contract-rerank \
    NASUS_RERANK_API_KEY="$NASUS_MODEL_PROVIDER_TOKEN" \
    NASUS_CODE_GRAPH_MODE=required \
    NASUS_CODE_GRAPH_BINARY="$NASUS_CODE_GRAPH_BINARY" \
    NASUS_AGENT_WORKFLOW_RUNTIME=temporal \
    NASUS_AGENT_GRAPH_RUNTIME=langgraph \
    NASUS_LANGGRAPH_CHECKPOINT_BACKEND=postgres \
    NASUS_LANGGRAPH_AGENT_LOOP_GRAPH=nasus-agent-loop \
    NASUS_TEMPORAL_ADDRESS="127.0.0.1:${TEMPORAL_PORT}" \
    NASUS_TEMPORAL_NAMESPACE=default \
    NASUS_TEMPORAL_TASK_QUEUE="$NASUS_TEMPORAL_TASK_QUEUE" \
    NASUS_TEMPORAL_AGENT_GOAL_WORKFLOW=NasusAgentGoalWorkflow \
    NASUS_TEMPORAL_QUERY_TIMEOUT_SECONDS=120 \
    NASUS_TEMPORAL_QUERY_POLL_INTERVAL_SECONDS=0.1 \
    NASUS_TEMPORAL_MAX_CONCURRENT_ACTIVITIES=1 \
    NASUS_RUNNER_MODE=http \
    NASUS_RUNNER_ENDPOINT="http://127.0.0.1:${NASUS_RUNNER_PORT}" \
    NASUS_RUNNER_SERVICE_TOKEN="$NASUS_RUNNER_SERVICE_TOKEN" \
    NASUS_RUNNER_ALLOWED_HOSTS=127.0.0.1 \
    NASUS_GIT_ALLOWED_HOSTS=github.com \
    NASUS_SOURCE_ALLOWED_LOCAL_ROOTS="$ROOT_DIR/tests/fixtures/system-image" \
    NASUS_SEED_DEMO_DATA=false \
    exec ./.venv/bin/python -m uvicorn apps.api.app.main:app --app-dir . --host 127.0.0.1 --port "$NASUS_API_PORT"
  ) >"$API_LOG" 2>&1 &
  API_PID=$!
  wait_for_api
}

if [[ "$KEEP_STACK" == false ]]; then
  compose down -v
  exit 0
fi

echo "==> Starting Docker infrastructure stack: $COMPOSE_PROJECT_NAME"
compose up -d postgres minio temporal
wait_for_postgres
wait_for_temporal

echo "==> Initializing MinIO bucket"
compose run --rm minio-init >/dev/null

echo "==> Verifying pgvector extension"
compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -c "SELECT extname FROM pg_extension WHERE extname = 'vector';" | grep -q "vector"

echo "==> Running Alembic migrations against Docker PostgreSQL"
(
  cd "$ROOT_DIR"
  NASUS_DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT}/${POSTGRES_DB}" \
  NASUS_AUTO_CREATE_TABLES=false \
  ./.venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head
)

echo "==> Verifying MinIO bucket versioning and object round-trip"
version_output="$(compose run --rm --entrypoint /bin/sh minio-init -c "
  set -e
  mc alias set nasus http://minio:9000 \"$MINIO_ROOT_USER\" \"$MINIO_ROOT_PASSWORD\" >/dev/null
  mc version info nasus/\"$NASUS_S3_BUCKET\"
" 2>/dev/null)"
echo "$version_output" | grep -qi "versioning is enabled"

object_output="$(compose run --rm --entrypoint /bin/sh minio-init -c "
  set -e
  mc alias set nasus http://minio:9000 \"$MINIO_ROOT_USER\" \"$MINIO_ROOT_PASSWORD\" >/dev/null
  printf 'nasus docker stack smoke' > /tmp/nasus-smoke.txt
  mc cp /tmp/nasus-smoke.txt nasus/\"$NASUS_S3_BUCKET\"/smoke/nasus-smoke.txt >/dev/null
  mc cat nasus/\"$NASUS_S3_BUCKET\"/smoke/nasus-smoke.txt
" 2>/dev/null)"
[[ "$object_output" == *"nasus docker stack smoke"* ]]

VERIFY_OUTPUT_DIR="$(mktemp -d -t nasus-docker-api-smoke.XXXXXX)"

echo "==> Starting real Playwright runner and isolated target fixture"
start_runner_dependencies

echo "==> Starting OpenAI-compatible model protocol fixture"
start_model_provider

echo "==> Starting Temporal Agent workflow worker with LangGraph PostgreSQL checkpoints"
start_workflow_worker

echo "==> Starting Nasus API against Docker PostgreSQL and MinIO"
start_api

echo "==> Creating a paused AgentGoal before Temporal worker restart"
NASUS_VERIFY_API_BASE="http://127.0.0.1:${NASUS_API_PORT}" \
NASUS_VERIFY_OUTPUT_DIR="$VERIFY_OUTPUT_DIR" \
NASUS_VERIFY_AUTH_TOKEN="$NASUS_AUTH_BEARER_TOKEN" \
"$ROOT_DIR/.venv/bin/python" - <<'PY'
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any


BASE = os.environ["NASUS_VERIFY_API_BASE"].rstrip("/")
OUT = Path(os.environ["NASUS_VERIFY_OUTPUT_DIR"])
AUTH_TOKEN = os.environ["NASUS_VERIFY_AUTH_TOKEN"]


def request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {AUTH_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


project = request(
    "POST",
    "/v1/projects",
    {"name": f"Temporal Worker Recovery {int(time.time())}"},
)
conversation = request(
    "POST",
    "/v1/conversations",
    {
        "space_type": "project",
        "space_id": project["id"],
        "title": "Temporal worker recovery verification",
    },
)
goal = request(
    "POST",
    "/v1/agent-goals",
    {
        "conversation_id": conversation["id"],
        "project_id": project["id"],
        "title": "Verify durable governance pause",
        "summary": "Pause at approval, restart the worker, then resume.",
        "steps": [
            {
                "id": "step_recovery_approval",
                "title": "Request governed approval",
                "status": "pending",
                "phase": "acting",
                "selected_tool_id": "approval.request",
                "tool_input_payload": {
                    "project_id": project["id"],
                    "purpose": "worker_restart_recovery",
                },
            }
        ],
    },
)
assert goal["status"] == "paused", goal
assert goal["pause_reason"] == "waiting_confirmation", goal
checkpoint = request("GET", f"/v1/agent-goals/{goal['id']}/checkpoint")
trace = request("GET", f"/v1/tool-invocations?agent_goal_id={goal['id']}")
assert checkpoint["status"] == "paused", checkpoint
assert len(trace) == 1 and trace[0]["status"] == "waiting_confirmation", trace
(OUT / "workflow_recovery.json").write_text(
    json.dumps(
        {
            "goal_id": goal["id"],
            "workflow_id": goal["workflow_id"],
            "tool_invocation_id": trace[0]["id"],
        }
    ),
    encoding="utf-8",
)
PY

echo "==> Restarting Temporal worker while AgentGoal is paused"
stop_workflow_worker
start_workflow_worker

echo "==> Resuming the same Temporal workflow after worker restart"
NASUS_VERIFY_API_BASE="http://127.0.0.1:${NASUS_API_PORT}" \
NASUS_VERIFY_OUTPUT_DIR="$VERIFY_OUTPUT_DIR" \
NASUS_VERIFY_AUTH_TOKEN="$NASUS_AUTH_BEARER_TOKEN" \
"$ROOT_DIR/.venv/bin/python" - <<'PY'
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any


BASE = os.environ["NASUS_VERIFY_API_BASE"].rstrip("/")
OUT = Path(os.environ["NASUS_VERIFY_OUTPUT_DIR"])
AUTH_TOKEN = os.environ["NASUS_VERIFY_AUTH_TOKEN"]
state = json.loads((OUT / "workflow_recovery.json").read_text(encoding="utf-8"))


def request(method: str, path: str) -> Any:
    req = urllib.request.Request(
        f"{BASE}{path}",
        method=method,
        headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


before = request("GET", f"/v1/agent-goals/{state['goal_id']}")
checkpoint = request("GET", f"/v1/agent-goals/{state['goal_id']}/checkpoint")
assert before["status"] == "paused", before
assert before["workflow_id"] == state["workflow_id"], before
assert (
    checkpoint["blocked_tool_invocation_id"] == state["tool_invocation_id"]
), checkpoint

completed = request("POST", f"/v1/agent-goals/{state['goal_id']}/resume")
assert completed["status"] == "completed", completed
assert completed["workflow_id"] == state["workflow_id"], completed
trace = request(
    "GET",
    f"/v1/tool-invocations?agent_goal_id={state['goal_id']}",
)
assert len(trace) == 1, trace
assert trace[0]["id"] == state["tool_invocation_id"], trace
assert trace[0]["status"] == "completed", trace
audit = request("GET", f"/v1/audit-events?agent_goal_id={state['goal_id']}")
actions = {item["action"] for item in audit}
required_actions = {
    "agent.goal.paused",
    "agent.goal.resume_requested",
    "agent.goal.resumed",
    "agent.goal.completed",
    "tool.invocation.gated",
    "tool.invocation.confirmed",
    "tool.invocation.completed",
}
assert required_actions.issubset(actions), sorted(required_actions - actions)
PY

echo "==> Running API smoke through system image and quality loop"
NASUS_VERIFY_API_BASE="http://127.0.0.1:${NASUS_API_PORT}" \
NASUS_VERIFY_ROOT="$ROOT_DIR" \
NASUS_VERIFY_OUTPUT_DIR="$VERIFY_OUTPUT_DIR" \
NASUS_VERIFY_S3_BUCKET="$NASUS_S3_BUCKET" \
NASUS_VERIFY_RUNNER_BASE_URL="http://127.0.0.1:${NASUS_RUNNER_TARGET_PORT}" \
NASUS_VERIFY_AUTH_TOKEN="$NASUS_AUTH_BEARER_TOKEN" \
"$ROOT_DIR/.venv/bin/python" - <<'PY'
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


BASE = os.environ["NASUS_VERIFY_API_BASE"].rstrip("/")
ROOT = Path(os.environ["NASUS_VERIFY_ROOT"])
OUT = Path(os.environ["NASUS_VERIFY_OUTPUT_DIR"])
BUCKET = os.environ["NASUS_VERIFY_S3_BUCKET"]
RUNNER_BASE_URL = os.environ["NASUS_VERIFY_RUNNER_BASE_URL"]
AUTH_TOKEN = os.environ["NASUS_VERIFY_AUTH_TOKEN"]


def request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {AUTH_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1000]
        raise AssertionError(f"{method} {path} failed with HTTP {exc.code}: {body}") from exc


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def s3_key(storage_ref: str) -> str:
    prefix = f"s3://{BUCKET}/"
    assert_true(storage_ref.startswith(prefix), f"expected S3 storage ref under {prefix}, got {storage_ref}")
    return storage_ref[len(prefix):]


def invoke(conversation_id: str, tool_id: str, input_payload: dict[str, Any]) -> Any:
    invocation = request(
        "POST",
        "/v1/tool-invocations",
        {
            "conversation_id": conversation_id,
            "tool_id": tool_id,
            "input": input_payload,
            "initiator_surface": "api",
            "initiator_actor": "user",
            "target_scope": "central",
        },
    )
    if invocation["status"] == "waiting_confirmation":
        invocation = request("POST", f"/v1/tool-invocations/{invocation['id']}/confirm")
    assert_true(invocation["status"] == "completed", f"{tool_id} did not complete: {invocation}")
    return invocation


health = request("GET", "/healthz")
assert_true(health.get("status") == "ok", "API health check failed")
readiness = request("GET", "/readyz")
assert_true(readiness.get("status") == "ready", "API readiness check failed")
assert_true(readiness["checks"]["database"]["details"]["backend"] == "postgresql", "API is not using PostgreSQL")
assert_true(readiness["checks"]["object_storage"]["details"]["backend"] == "s3", "API is not using MinIO/S3")
assert_true(
    readiness["checks"]["code_intelligence"]["details"]["backend"] == "tree-sitter",
    "API is not using the Tree-sitter code intelligence adapter",
)
assert_true(
    readiness["checks"]["automation_runner"]["details"]["backend"] == "http_playwright",
    "API is not connected to the real Playwright runner",
)
assert_true(
    readiness["checks"]["agent_workflow"]["details"]["backend"] == "temporal",
    "API is not connected to Temporal",
)
assert_true(
    readiness["checks"]["agent_checkpoint"]["details"]["backend"] == "postgres",
    "API is not using PostgreSQL LangGraph checkpoints",
)
assert_true(
    readiness["checks"]["model_routes"]["details"]["backend"] == "live",
    f"model routes are not live: {readiness['checks']['model_routes']}",
)
for model_route in ("chat", "embedding", "rerank"):
    connection = request(
        "POST",
        "/v1/settings/test-connection",
        {"model_route": model_route},
    )
    assert_true(connection["ok"] is True, f"{model_route} connection failed: {connection}")
    assert_true(connection["runtime_mode"] == "live", f"{model_route} is not live: {connection}")
    assert_true(
        connection["provider"] == "openai_compatible",
        f"{model_route} did not use the OpenAI-compatible adapter: {connection}",
    )

tools = request("GET", "/v1/tools/catalog")
tool_ids = {tool["tool_id"] for tool in tools}
required_tools = {
    "system_image.sources.register",
    "system_image.sources.ingest",
    "system_image.context.materialize",
    "system_image.baseline.initialize",
    "version.create",
    "version.inputs.import",
    "version.branch.bind",
    "version.participants.assign",
    "version.risk.initialize",
    "us.task.start",
    "quality.scope.generate",
    "quality.scenario.generate",
    "quality.plan.generate",
    "quality.case.generate",
    "automation.generate",
    "quality.change-doc.generate",
    "run.start",
    "release.assess",
    "approval.request",
    "approval.decide",
    "release.decision.submit",
    "baseline.promote",
}
missing = sorted(required_tools - tool_ids)
assert_true(not missing, f"tool catalog is missing: {missing}")

project = request("POST", "/v1/projects", {"name": f"Docker API Smoke {int(time.time())}"})
project_id = project["id"]
conversation = request(
    "POST",
    "/v1/conversations",
    {"space_type": "project", "space_id": project_id, "title": project["name"]},
)
conversation_id = conversation["id"]

fixture = ROOT / "tests" / "fixtures" / "system-image"
agent_response = request(
    "POST",
    f"/v1/conversations/{conversation_id}/messages",
    {
        "content": (
            "Build the official system image with "
            f"code path {fixture / 'code'}, "
            f"US docs path {fixture / 'us'}, "
            f"tests path {fixture / 'tests'}"
        )
    },
)
goal = agent_response.get("agent_goal")
assert_true(isinstance(goal, dict), f"conversation did not create an AgentGoal: {agent_response}")
goal_id = goal["id"]
assert_true(goal["status"] == "paused", f"AgentGoal did not pause at its governance gate: {goal}")
assert_true(goal["pause_reason"] == "waiting_confirmation", f"unexpected AgentGoal pause: {goal}")
assert_true(goal.get("workflow_id", "").startswith("nasus-agent-goal-"), "Temporal workflow ID was not attached")

trace = request("GET", f"/v1/tool-invocations?agent_goal_id={goal_id}")
trace_by_tool = {item["tool_id"]: item for item in trace}
expected_agent_tools = {
    "system_image.sources.register",
    "system_image.sources.ingest",
    "system_image.context.materialize",
    "system_image.baseline.initialize",
}
assert_true(
    expected_agent_tools.issubset(trace_by_tool),
    f"AgentGoal did not execute the complete system image plan: {trace_by_tool}",
)
baseline_invocation = trace_by_tool["system_image.baseline.initialize"]
assert_true(
    baseline_invocation["status"] == "waiting_confirmation",
    f"baseline initialization did not stop at confirmation: {baseline_invocation}",
)

resumed_goal = request("POST", f"/v1/agent-goals/{goal_id}/resume")
assert_true(resumed_goal["status"] == "completed", f"Temporal AgentGoal did not complete after resume: {resumed_goal}")
assert_true(resumed_goal["workflow_id"] == goal["workflow_id"], "AgentGoal lost its Temporal workflow identity")

image = request("GET", f"/v1/projects/{project_id}/system-image")
assert_true(image["project"]["system_image_status"] == "ready", "official system image was not marked ready")
assert_true(image["build_state"]["status"] == "ready", "system image build state was not ready")
sources = {source["source_type"]: source for source in image["sources"]}
assert_true(set(sources) == {"code", "us_doc", "test_asset"}, "three required source groups were not registered")
for source_type, source in sources.items():
    assert_true(source["ingestion_status"] == "indexed", f"{source_type} was not indexed")
    assert_true(source["permission_status"] == "allowed", f"{source_type} permission was not allowed")
    assert_true(source["content_hash"].startswith("sha256:"), f"{source_type} content hash was not recorded")
    assert_true(source["file_count"] > 0, f"{source_type} file count was not recorded")
    assert_true(source["byte_count"] > 0, f"{source_type} byte count was not recorded")

chunks = image["chunks"]
assert_true(len(chunks) >= 3, "expected raw asset chunks for code, US, and test sources")
assert_true(all(chunk["content_ref"].startswith(f"s3://{BUCKET}/") for chunk in chunks), "raw asset chunks did not use MinIO/S3")
object_types = {item["type"] for item in image["objects"]}
relationship_types = {item["relationship_type"] for item in image["relationships"]}
metric_groups = {item["metric_group"] for item in image["metric_snapshots"]}
assert_true(
    {"CodeClass", "CodeMethod", "USWorkItem", "TestCase"}.issubset(object_types),
    f"materialized object types are incomplete: {sorted(object_types)}",
)
assert_true({"implements", "impacts", "covers"}.issubset(relationship_types), "materialized relationships are incomplete")
assert_true({"code_quality", "us_completion_quality", "test_quality"}.issubset(metric_groups), "metric snapshots are incomplete")
assert_true(image["embedding_records"], "embedding records were not created")
assert_true(image["retrieval_runs"], "retrieval runs were not created")
assert_true(image["rerank_records"], "rerank records were not created")
assert_true(image["task_contexts"], "task contexts were not created")
assert_true(image["quality_profiles"], "quality profiles were not created")

initial_workspace = request("GET", f"/v1/projects/{project_id}")
initial_us_ids = {item["id"] for item in initial_workspace["us_items"]}
assert_true(initial_us_ids, "system image initialization did not materialize initial US evidence")

version_creation = invoke(
    conversation_id,
    "version.create",
    {
        "project_id": project_id,
        "name": "2026 Production Verification",
    },
)
version_refs = [
    ref
    for ref in version_creation["result"]["object_refs"]
    if ref.startswith("version:")
]
assert_true(version_refs, "version.create did not return a version ref")
version_id = version_refs[0].split(":", 1)[1]
us_id = f"us-docker-release-{int(time.time())}"

invoke(
    conversation_id,
    "version.branch.bind",
    {
        "project_id": project_id,
        "version_id": version_id,
        "branch_name": "release/docker-production-verification",
    },
)
invoke(
    conversation_id,
    "version.inputs.import",
    {
        "project_id": project_id,
        "version_id": version_id,
        "us_items": [
            {
                "id": us_id,
                "title": "Verify the production quality release path",
                "owner": "Unassigned",
            }
        ],
    },
)
invoke(
    conversation_id,
    "version.participants.assign",
    {
        "project_id": project_id,
        "version_id": version_id,
        "assignments": [{"us_id": us_id, "owner": "Release QA"}],
    },
)
invoke(
    conversation_id,
    "version.risk.initialize",
    {
        "project_id": project_id,
        "version_id": version_id,
    },
)
invoke(
    conversation_id,
    "us.task.start",
    {
        "project_id": project_id,
        "version_id": version_id,
        "us_id": us_id,
    },
)

workspace = request("GET", f"/v1/projects/{project_id}")
assert_true(workspace["current_version_id"] == version_id, "new version is not the active workspace version")
assert_true(
    [item["id"] for item in workspace["us_items"]] == [us_id],
    f"active version US projection leaked another version: {workspace['us_items']}",
)
assert_true(workspace["us_items"][0]["owner"] == "Release QA", "version participant assignment was not retained")
assert_true(workspace["us_items"][0]["status"] == "analysis", "US quality task was not started")

for tool_id, tool_input in [
    ("quality.scope.generate", {}),
    ("quality.scenario.generate", {}),
    ("quality.plan.generate", {}),
    ("quality.case.generate", {}),
    ("automation.generate", {}),
    ("run.start", {"base_url": RUNNER_BASE_URL}),
    ("quality.change-doc.generate", {}),
    ("release.assess", {}),
]:
    invoke(
        conversation_id,
        tool_id,
        {
            "project_id": project_id,
            "version_id": version_id,
            "us_id": us_id,
            **tool_input,
        },
    )

workspace = request("GET", f"/v1/projects/{project_id}")
assert_true(
    workspace["quality_loop_state"]["status"] == "ready_for_release",
    (
        "quality loop did not reach ready_for_release: "
        f"state={workspace['quality_loop_state']}, "
        f"runs={workspace.get('runs', [])[:1]}, "
        f"failures={workspace.get('failure_reports', [])[:1]}"
    ),
)
assert_true(workspace["quality_asset_pack"]["status"] == "completed", "quality asset pack was not completed")
assert_true(workspace["release_decision"] is None, "release.assess must not create a formal ReleaseDecision")
assert_true(workspace["execution_evidence"], "execution evidence was not produced")
assert_true(
    all(item["storage_ref"].startswith(f"s3://{BUCKET}/") for item in workspace["execution_evidence"]),
    "execution evidence did not use MinIO/S3",
)

release = request("GET", f"/v1/projects/{project_id}/release-readiness")
assert_true(release["status"] == "Ready for release review", "release readiness was not ready for review")
assert_true(release["score"] >= 80, "release score is below ready threshold")
approval_request = invoke(
    conversation_id,
    "approval.request",
    {
        "project_id": project_id,
        "purpose": "release_decision",
        "target_ref": f"release_readiness:{release['version_id']}",
        "evidence_refs": [f"release_readiness:{release['version_id']}"],
    },
)
approval_refs = [
    ref
    for ref in approval_request["result"]["object_refs"]
    if ref.startswith("approval:")
]
assert_true(approval_refs, "approval.request did not return an approval ref")
approval_id = approval_refs[0].split(":", 1)[1]
invoke(
    conversation_id,
    "approval.decide",
    {
        "project_id": project_id,
        "approval_id": approval_id,
        "decision": "approved",
        "rationale": "Docker stack smoke approved release decision submission.",
    },
)
release_submit = invoke(
    conversation_id,
    "release.decision.submit",
    {
        "project_id": project_id,
        "version_id": release["version_id"],
        "us_id": us_id,
        "approval_id": approval_id,
    },
)
workspace = request("GET", f"/v1/projects/{project_id}")
assert_true(workspace["release_decision"]["status"] == "ready", "release decision was not ready after submission")
assert_true(workspace["release_decision"]["approval_ref"] == f"approval:{approval_id}", "release decision approval ref was not attached")
assert_true(
    any(ref.startswith("execution_evidence:") for ref in workspace["release_decision"]["evidence_refs"]),
    "release decision did not retain execution evidence refs",
)
baseline_promotion = invoke(
    conversation_id,
    "baseline.promote",
    {
        "project_id": project_id,
        "version_id": release["version_id"],
        "us_id": us_id,
        "approval_id": approval_id,
    },
)

baseline_audit = request("GET", f"/v1/audit-events?tool_invocation_id={baseline_invocation['id']}")
actions = {event["action"] for event in baseline_audit}
assert_true("tool.invocation.gated" in actions, "baseline confirmation gate was not audited")
assert_true("tool.invocation.confirmed" in actions, "baseline confirmation was not audited")
assert_true("tool.invocation.completed" in actions, "baseline completion was not audited")

release_submit_audit = request("GET", f"/v1/audit-events?tool_invocation_id={release_submit['id']}")
release_submit_actions = {event["action"] for event in release_submit_audit}
assert_true("tool.invocation.executing" in release_submit_actions, "release decision submission execution was not audited")
assert_true("tool.invocation.completed" in release_submit_actions, "release decision submission was not audited")
promotion_audit = request("GET", f"/v1/audit-events?tool_invocation_id={baseline_promotion['id']}")
promotion_actions = {event["action"] for event in promotion_audit}
assert_true("tool.invocation.executing" in promotion_actions, "baseline promotion execution was not audited")
assert_true("tool.invocation.completed" in promotion_actions, "baseline promotion was not audited")

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "project_id").write_text(project_id, encoding="utf-8")
(OUT / "goal_id").write_text(goal_id, encoding="utf-8")
(OUT / "chunk_key").write_text(s3_key(chunks[0]["content_ref"]), encoding="utf-8")
report_evidence = next(
    (
        item
        for item in workspace["execution_evidence"]
        if item["evidence_type"] == "report"
    ),
    None,
)
assert_true(report_evidence is not None, "runner result report evidence was not produced")
(OUT / "run_id").write_text(report_evidence["run_id"], encoding="utf-8")
(OUT / "evidence_key").write_text(s3_key(report_evidence["storage_ref"]), encoding="utf-8")
(OUT / "evidence_hash").write_text(report_evidence["content_hash"], encoding="utf-8")
print(f"API smoke completed for project {project_id}")
PY

echo "==> Verifying API artifacts are readable from MinIO"
chunk_key="$(cat "$VERIFY_OUTPUT_DIR/chunk_key")"
evidence_key="$(cat "$VERIFY_OUTPUT_DIR/evidence_key")"

chunk_payload="$(compose run --rm --entrypoint /bin/sh minio-init -c "
  set -e
  mc alias set nasus http://minio:9000 \"$MINIO_ROOT_USER\" \"$MINIO_ROOT_PASSWORD\" >/dev/null
  mc cat nasus/\"$NASUS_S3_BUCKET\"/\"$chunk_key\"
" 2>/dev/null)"
echo "$chunk_payload" | grep -q '"project_id"'
echo "$chunk_payload" | grep -q '"content_hash"'

evidence_payload="$(compose run --rm --entrypoint /bin/sh minio-init -c "
  set -e
  mc alias set nasus http://minio:9000 \"$MINIO_ROOT_USER\" \"$MINIO_ROOT_PASSWORD\" >/dev/null
  mc cat nasus/\"$NASUS_S3_BUCKET\"/\"$evidence_key\"
" 2>/dev/null)"
echo "$evidence_payload" | grep -q '"run_id"'
echo "$evidence_payload" | grep -q '"status"'
echo "$evidence_payload" | grep -q '"runner_status"'

echo "==> Verifying API writes are persisted in Docker PostgreSQL"
project_id="$(cat "$VERIFY_OUTPUT_DIR/project_id")"
goal_id="$(cat "$VERIFY_OUTPUT_DIR/goal_id")"
run_id="$(cat "$VERIFY_OUTPUT_DIR/run_id")"
evidence_hash="$(cat "$VERIFY_OUTPUT_DIR/evidence_hash")"
run_count="$(compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1 \
  -c "SELECT count(*) FROM runs WHERE project_id = '${project_id}' AND id = '${run_id}' AND status = 'passed';")"
[[ "$run_count" == "1" ]]

evidence_count="$(compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1 \
  -c "SELECT count(*) FROM execution_evidence WHERE project_id = '${project_id}' AND run_id = '${run_id}' AND content_hash = '${evidence_hash}' AND storage_ref LIKE 's3://%';")"
[[ "$evidence_count" -ge 1 ]]

goal_count="$(compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1 \
  -c "SELECT count(*) FROM agent_goals WHERE id = '${goal_id}' AND status = 'completed' AND workflow_id LIKE 'nasus-agent-goal-%';")"
[[ "$goal_count" == "1" ]]

checkpoint_thread_id="nasus-agent-loop:${goal_id}"
checkpoint_count="$(compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1 \
  -c "SELECT count(*) FROM checkpoints WHERE thread_id = '${checkpoint_thread_id}';")"
[[ "$checkpoint_count" -ge 1 ]]

echo "==> Restarting API to verify PostgreSQL persistence"
stop_api
start_api
NASUS_VERIFY_API_BASE="http://127.0.0.1:${NASUS_API_PORT}" \
NASUS_VERIFY_PROJECT_ID="$project_id" \
NASUS_VERIFY_GOAL_ID="$goal_id" \
NASUS_VERIFY_S3_BUCKET="$NASUS_S3_BUCKET" \
NASUS_VERIFY_AUTH_TOKEN="$NASUS_AUTH_BEARER_TOKEN" \
"$ROOT_DIR/.venv/bin/python" - <<'PY'
from __future__ import annotations

import json
import os
import urllib.request


BASE = os.environ["NASUS_VERIFY_API_BASE"].rstrip("/")
PROJECT_ID = os.environ["NASUS_VERIFY_PROJECT_ID"]
GOAL_ID = os.environ["NASUS_VERIFY_GOAL_ID"]
BUCKET = os.environ["NASUS_VERIFY_S3_BUCKET"]
AUTH_TOKEN = os.environ["NASUS_VERIFY_AUTH_TOKEN"]


def get(path: str):
    request = urllib.request.Request(
        f"{BASE}{path}",
        headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


workspace = get(f"/v1/projects/{PROJECT_ID}")
image = get(f"/v1/projects/{PROJECT_ID}/system-image")
goal = get(f"/v1/agent-goals/{GOAL_ID}")
assert workspace["project"]["system_image_status"] == "ready"
assert workspace["quality_loop_state"]["status"] == "ready_for_release"
assert workspace["release_decision"]["status"] == "ready"
assert image["build_state"]["status"] == "ready"
assert image["chunks"]
assert goal["status"] == "completed"
assert goal["workflow_id"].startswith("nasus-agent-goal-")
assert workspace["execution_evidence"]
assert all(item["content_ref"].startswith(f"s3://{BUCKET}/") for item in image["chunks"])
assert all(item["storage_ref"].startswith(f"s3://{BUCKET}/") for item in workspace["execution_evidence"])
print(f"Persistence smoke passed for project {PROJECT_ID}")
PY

echo "==> Verifying all model routes traversed the live HTTP adapters"
model_stats="$(
  curl -fsS \
    -H "Authorization: Bearer ${NASUS_MODEL_PROVIDER_TOKEN}" \
    "http://127.0.0.1:${NASUS_MODEL_PROVIDER_PORT}/__stats"
)"
NASUS_VERIFY_MODEL_STATS="$model_stats" "$ROOT_DIR/.venv/bin/python" - <<'PY'
import json
import os


stats = json.loads(os.environ["NASUS_VERIFY_MODEL_STATS"])["requests"]
for route in ("chat", "embedding", "rerank"):
    if int(stats.get(route, 0)) < 1:
        raise AssertionError(f"{route} adapter did not call the model protocol fixture: {stats}")
print(f"Model protocol calls verified: {stats}")
PY

echo "Docker stack verification passed."
echo "PostgreSQL: 127.0.0.1:${POSTGRES_PORT}"
echo "MinIO API: 127.0.0.1:${MINIO_API_PORT}"
echo "Temporal: 127.0.0.1:${TEMPORAL_PORT}"
echo "Model protocol fixture: 127.0.0.1:${NASUS_MODEL_PROVIDER_PORT}"
echo "Nasus API smoke: 127.0.0.1:${NASUS_API_PORT}"
echo "To stop and remove verification containers: COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME scripts/verify-docker-stack.sh --down"
