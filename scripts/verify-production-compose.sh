#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-nasus_production_contract}"

compose() {
  COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" \
  docker compose \
    --profile app \
    --profile temporal \
    -f "$ROOT_DIR/docker-compose.yml" \
    "$@"
}

echo "==> Validating production-like Docker Compose topology"
config_file="$(mktemp)"
trap 'rm -f "$config_file"' EXIT
compose config --format json >"$config_file"

echo "==> Verifying required services are declared"
services="$(compose config --services | sort)"
for service in postgres minio minio-init api-migrate runner api portal temporal workflow-service temporal-ui; do
  echo "$services" | grep -qx "$service"
done

echo "==> Verifying workflow worker runtime configuration"
python3 - "$config_file" <<'PY'
from __future__ import annotations

import json
import sys


with open(sys.argv[1], encoding="utf-8") as handle:
    services = json.load(handle)["services"]

api_environment = services["api"].get("environment", {})
workflow = services["workflow-service"]
workflow_environment = workflow.get("environment", {})

shared_runtime_keys = {
    "NASUS_ENV",
    "NASUS_DATABASE_URL",
    "NASUS_AUTO_CREATE_TABLES",
    "NASUS_S3_ENDPOINT",
    "NASUS_S3_BUCKET",
    "NASUS_S3_ACCESS_KEY",
    "NASUS_S3_SECRET_KEY",
    "NASUS_SOURCE_CACHE_DIR",
    "NASUS_GIT_ALLOWED_HOSTS",
    "NASUS_CODE_GRAPH_MODE",
    "NASUS_CODE_GRAPH_BINARY",
    "NASUS_CODE_GRAPH_CACHE_DIR",
    "NASUS_AUTH_MODE",
    "NASUS_AUTH_BEARER_TOKEN",
    "NASUS_RATE_LIMIT_ENABLED",
    "NASUS_RATE_LIMIT_BACKEND",
    "NASUS_RATE_LIMIT_WINDOW_SECONDS",
    "NASUS_RATE_LIMIT_AUTH_PER_WINDOW",
    "NASUS_RATE_LIMIT_AGENT_PER_WINDOW",
    "NASUS_RATE_LIMIT_API_PER_WINDOW",
    "NASUS_SETTINGS_ENCRYPTION_SECRET",
    "NASUS_DEFAULT_PROVIDER",
    "NASUS_EMBEDDING_PROVIDER",
    "NASUS_RERANK_PROVIDER",
    "NASUS_TEMPORAL_ADDRESS",
    "NASUS_TEMPORAL_NAMESPACE",
    "NASUS_TEMPORAL_TASK_QUEUE",
    "NASUS_TEMPORAL_AGENT_GOAL_WORKFLOW",
    "NASUS_RUNNER_MODE",
    "NASUS_RUNNER_ENDPOINT",
    "NASUS_RUNNER_SERVICE_TOKEN",
    "NASUS_SEED_DEMO_DATA",
}

missing_api = sorted(shared_runtime_keys - set(api_environment))
missing_workflow = sorted(shared_runtime_keys - set(workflow_environment))
if missing_api:
    raise SystemExit(f"api is missing required runtime keys: {', '.join(missing_api)}")
if missing_workflow:
    raise SystemExit(
        "workflow-service did not inherit required API runtime keys: "
        + ", ".join(missing_workflow)
    )

for key in shared_runtime_keys:
    if workflow_environment.get(key) != api_environment.get(key):
        raise SystemExit(
            f"workflow-service runtime value for {key} differs from api"
        )

expected_durable_runtime = {
    "NASUS_AGENT_WORKFLOW_RUNTIME": "temporal",
    "NASUS_AGENT_GRAPH_RUNTIME": "langgraph",
    "NASUS_LANGGRAPH_CHECKPOINT_BACKEND": "postgres",
}
for service_name, environment in (
    ("api", api_environment),
    ("workflow-service", workflow_environment),
):
    invalid_runtime = {
        key: environment.get(key)
        for key, expected in expected_durable_runtime.items()
        if environment.get(key) != expected
    }
    if invalid_runtime:
        raise SystemExit(
            f"{service_name} durable Agent runtime is invalid: {invalid_runtime}"
        )

expected_module = "apps.api.app.infrastructure.workflow.agent_goal_workflow_worker"
if expected_module not in workflow.get("command", []):
    raise SystemExit("workflow-service does not start the canonical Temporal worker module")
PY

if [[ "${NASUS_VERIFY_PRODUCTION_COMPOSE_BUILD:-false}" == "true" ]]; then
  echo "==> Building API, Runner, and Portal container images"
  compose build api runner portal
fi

echo "Production-like Docker Compose topology verification passed."
