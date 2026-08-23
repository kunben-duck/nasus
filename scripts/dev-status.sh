#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/dev-runtime-env.sh"

PID_DIR="$NASUS_DEV_RUNTIME_DIR/pids"

for component in runner workflow api portal; do
  pid_file="$PID_DIR/$component.pid"
  if [[ -f "$pid_file" ]] && kill -0 "$(<"$pid_file")" >/dev/null 2>&1; then
    echo "$component: running (pid $(<"$pid_file"))"
  else
    echo "$component: stopped"
  fi
done

if readiness="$(curl -fsS "http://127.0.0.1:${NASUS_API_PORT}/readyz" 2>/dev/null)"; then
  NASUS_DEV_READINESS="$readiness" "$ROOT_DIR/.venv/bin/python" - <<'PY'
import json
import os

payload = json.loads(os.environ["NASUS_DEV_READINESS"])
checks = payload.get("checks", {})
for name in ("database", "object_storage", "automation_runner", "agent_workflow", "agent_checkpoint", "model_routes"):
    check = checks.get(name, {})
    details = check.get("details", {})
    backend = details.get("backend", "unknown")
    print(f"{name}: {check.get('status', 'unknown')} ({backend})")
PY
else
  echo "api readiness: unavailable"
fi
