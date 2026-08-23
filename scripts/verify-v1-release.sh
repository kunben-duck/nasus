#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ID="${NASUS_RELEASE_RUN_ID:-$(date +%s)-$$}"
DOCKER_PROJECT="${NASUS_RELEASE_COMPOSE_PROJECT:-nasus_v1_release_${RUN_ID//[^a-zA-Z0-9]/_}}"
POSTGRES_PORT="${NASUS_RELEASE_POSTGRES_PORT:-55$(( (10#$$ % 80) + 400 ))}"
MINIO_API_PORT="${NASUS_RELEASE_MINIO_API_PORT:-59$(( (10#$$ % 80) + 100 ))}"
MINIO_CONSOLE_PORT="${NASUS_RELEASE_MINIO_CONSOLE_PORT:-59$(( (10#$$ % 80) + 200 ))}"
NASUS_API_PORT="${NASUS_RELEASE_API_PORT:-18$(( (10#$$ % 80) + 100 ))}"
E2E_API_PORT="${NASUS_RELEASE_E2E_API_PORT:-18084}"
E2E_PORTAL_PORT="${NASUS_RELEASE_E2E_PORTAL_PORT:-4174}"
RUNNER_PORT="${NASUS_RELEASE_RUNNER_PORT:-19$(( (10#$$ % 80) + 100 ))}"
RUNNER_TARGET_PORT="${NASUS_RELEASE_RUNNER_TARGET_PORT:-19$(( (10#$$ % 80) + 200 ))}"
TEMPORAL_PORT="${NASUS_RELEASE_TEMPORAL_PORT:-17$(( (10#$$ % 80) + 300 ))}"

cleanup() {
  COMPOSE_PROJECT_NAME="$DOCKER_PROJECT" \
  POSTGRES_PORT="$POSTGRES_PORT" \
  MINIO_API_PORT="$MINIO_API_PORT" \
  MINIO_CONSOLE_PORT="$MINIO_CONSOLE_PORT" \
  NASUS_API_PORT="$NASUS_API_PORT" \
  TEMPORAL_PORT="$TEMPORAL_PORT" \
  "$ROOT_DIR/scripts/verify-docker-stack.sh" --down >/dev/null 2>&1 || true
}

run_step() {
  local label="$1"
  shift
  printf '\n==> %s\n' "$label"
  "$@"
}

trap cleanup EXIT

cd "$ROOT_DIR"

run_step "Verify repository release hygiene" npm run verify:release-hygiene
run_step "Lint Web portal" npm run lint:portal
run_step "Check Web portal architecture boundaries" npm run test:portal-boundaries
run_step "Build Web portal" npm run build:portal
run_step "Run isolated Playwright runner tests" npm run test:runner
run_step "Run backend unit and contract tests" ./.venv/bin/python -m pytest apps/api/tests tests/test_docker_stack_contract.py tests/test_ddd_boundaries.py -q
run_step "Verify real Codebase Memory entity and relationship contract" npm run verify:code-graph-provider
run_step "Validate production Compose and durable runtime topology" npm run verify:production-compose
run_step "Exercise PostgreSQL and MinIO backup/restore" npm run verify:backup-restore
run_step "Run agent-first browser E2E" env \
  PLAYWRIGHT_API_PORT="$E2E_API_PORT" \
  PLAYWRIGHT_PORTAL_PORT="$E2E_PORTAL_PORT" \
  NASUS_PORTAL_API_PROXY="http://127.0.0.1:${E2E_API_PORT}" \
  npm run test:e2e
run_step "Run Web/API smoke journey" env \
  API_URL="http://127.0.0.1:${E2E_API_PORT}" \
  PORTAL_URL="http://127.0.0.1:${E2E_PORTAL_PORT}" \
  NASUS_PORTAL_API_PROXY="http://127.0.0.1:${E2E_API_PORT}" \
  SMOKE_API_COMMAND="./.venv/bin/python -m uvicorn apps.api.app.main:app --app-dir . --host 127.0.0.1 --port ${E2E_API_PORT}" \
  SMOKE_PORTAL_COMMAND="npm --prefix apps/portal run dev -- --host 127.0.0.1 --port ${E2E_PORTAL_PORT}" \
  npm run test:smoke
run_step "Run Docker infrastructure and persistence verification" env \
  COMPOSE_PROJECT_NAME="$DOCKER_PROJECT" \
  POSTGRES_PORT="$POSTGRES_PORT" \
  MINIO_API_PORT="$MINIO_API_PORT" \
  MINIO_CONSOLE_PORT="$MINIO_CONSOLE_PORT" \
  NASUS_API_PORT="$NASUS_API_PORT" \
  NASUS_RUNNER_PORT="$RUNNER_PORT" \
  NASUS_RUNNER_TARGET_PORT="$RUNNER_TARGET_PORT" \
  NASUS_MODEL_PROVIDER_PORT="$((NASUS_API_PORT + 10))" \
  TEMPORAL_PORT="$TEMPORAL_PORT" \
  "$ROOT_DIR/scripts/verify-docker-stack.sh"

printf '\nV1 release verification passed.\n'
printf 'Evidence: portal build, backend tests, browser E2E, production runtime validation, backup/restore, live model HTTP adapters, real Runner, Temporal/LangGraph Agent flow, PostgreSQL/MinIO persistence.\n'
