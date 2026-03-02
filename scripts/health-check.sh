#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BACKEND_PORT="${BACKEND_PORT:-8080}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BASE_URL="${BASE_URL:-http://localhost:${BACKEND_PORT}/api}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:${FRONTEND_PORT}}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-180}"
AUTO_UP=1
NO_CLEANUP=0

TOKEN=""
US_ID=""

usage() {
  cat <<'USAGE'
Usage: ./scripts/health-check.sh [options]

Options:
  --skip-up       Skip `docker compose up -d --wait`
  --no-cleanup    Keep generated test data
  --timeout N     Wait timeout in seconds (default: 180)
  -h, --help      Show this help
USAGE
}

log() {
  printf '[health-check] %s\n' "$*"
}

fail() {
  printf '[health-check] ERROR: %s\n' "$*" >&2
  exit 1
}

json_get() {
  local path="$1"
  local payload="${2:-$HTTP_BODY}"
  python3 - "$path" "$payload" <<'PY'
import json
import re
import sys

path = sys.argv[1]
text = sys.argv[2].strip()
if not text:
    sys.exit(1)

obj = json.loads(text)


def lookup(cur, key):
    token = key
    while token:
        m = re.match(r'^([^\[\]]+)?(?:\[(\d+)\])?(.*)$', token)
        if not m:
            raise KeyError(token)
        name, idx, rest = m.groups()
        if name:
            if not isinstance(cur, dict):
                raise KeyError(name)
            cur = cur.get(name)
        if idx is not None:
            if not isinstance(cur, list):
                raise IndexError(idx)
            cur = cur[int(idx)]
        token = rest
    return cur

try:
    current = obj
    if path:
        for part in path.split('.'):
            if part:
                current = lookup(current, part)
except Exception:
    sys.exit(1)

if isinstance(current, (dict, list)):
    print(json.dumps(current, ensure_ascii=False))
elif current is None:
    print("")
else:
    print(current)
PY
}

json_len() {
  local path="$1"
  local payload="${2:-$HTTP_BODY}"
  python3 - "$path" "$payload" <<'PY'
import json
import sys

path = sys.argv[1]
obj = json.loads(sys.argv[2] or 'null')
cur = obj
if path:
    for part in path.split('.'):
        if not part:
            continue
        if '[' in part:
            key, idx = part.split('[', 1)
            idx = int(idx[:-1])
            cur = cur.get(key)[idx]
        elif isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            cur = cur[int(part)]
        else:
            cur = None
if cur is None:
    print(0)
elif isinstance(cur, (list, dict, str)):
    print(len(cur))
else:
    print(1)
PY
}

ensure_api_success() {
  local payload="$1"
  python3 - "$payload" <<'PY'
import json
import sys

text = sys.argv[1].strip()
if not text:
    sys.exit(0)
obj = json.loads(text)
if isinstance(obj, dict) and 'success' in obj and not obj['success']:
    sys.exit(1)
PY
}

wait_for_backend() {
  local deadline=$((SECONDS + TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    local body
    body="$(curl -fsS "${BASE_URL}/actuator/health" 2>/dev/null || true)"
    if [[ -n "$body" ]]; then
      local status
      status="$(json_get "status" "$body" 2>/dev/null || true)"
      if [[ "$status" == "UP" ]]; then
        return 0
      fi
    fi
    sleep 2
  done
  return 1
}

wait_for_frontend() {
  local deadline=$((SECONDS + TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    if curl -fsS "${FRONTEND_URL}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

HTTP_BODY=""
HTTP_CODE=""

api_call() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  local auth_token="${4:-}"
  local url="${BASE_URL}${path}"

  local response
  if [[ -n "$body" ]]; then
    if [[ -n "$auth_token" ]]; then
      response="$(curl -sS -X "$method" "$url" \
        -H 'Accept: application/json' \
        -H 'Content-Type: application/json' \
        -H "Authorization: Bearer ${auth_token}" \
        -d "$body" \
        -w $'\n%{http_code}')"
    else
      response="$(curl -sS -X "$method" "$url" \
        -H 'Accept: application/json' \
        -H 'Content-Type: application/json' \
        -d "$body" \
        -w $'\n%{http_code}')"
    fi
  else
    if [[ -n "$auth_token" ]]; then
      response="$(curl -sS -X "$method" "$url" \
        -H 'Accept: application/json' \
        -H "Authorization: Bearer ${auth_token}" \
        -w $'\n%{http_code}')"
    else
      response="$(curl -sS -X "$method" "$url" \
        -H 'Accept: application/json' \
        -w $'\n%{http_code}')"
    fi
  fi

  HTTP_BODY="${response%$'\n'*}"
  HTTP_CODE="${response##*$'\n'}"

  if [[ ! "$HTTP_CODE" =~ ^2 ]]; then
    printf '[health-check] HTTP %s %s %s failed\n' "$HTTP_CODE" "$method" "$path" >&2
    printf '%s\n' "$HTTP_BODY" >&2
    return 1
  fi

  if ! ensure_api_success "$HTTP_BODY"; then
    printf '[health-check] API success=false for %s %s\n' "$method" "$path" >&2
    printf '%s\n' "$HTTP_BODY" >&2
    return 1
  fi
}

must_have() {
  local value="$1"
  local message="$2"
  [[ -n "$value" ]] || fail "$message"
}

cleanup_resources() {
  if [[ "$NO_CLEANUP" -eq 1 ]]; then
    log "Skip cleanup (--no-cleanup)."
    return
  fi
  if [[ -z "$TOKEN" || -z "$US_ID" ]]; then
    return
  fi

  log "Cleaning generated data..."

  local tc_resp tc_ids tc_id script_resp script_id
  tc_resp="$(curl -sS -X GET "${BASE_URL}/test-cases/user-story/${US_ID}" \
    -H 'Accept: application/json' \
    -H "Authorization: Bearer ${TOKEN}" || true)"
  tc_ids="$(python3 - "$tc_resp" <<'PY'
import json
import sys
try:
    data = json.loads(sys.argv[1] or '{}').get('data') or []
    print(' '.join(str(item.get('id')) for item in data if item.get('id')))
except Exception:
    print('')
PY
)"

  for tc_id in $tc_ids; do
    script_resp="$(curl -sS -X GET "${BASE_URL}/test-scripts/test-case/${tc_id}" \
      -H 'Accept: application/json' \
      -H "Authorization: Bearer ${TOKEN}" || true)"
    script_id="$(python3 - "$script_resp" <<'PY'
import json
import sys
try:
    data = json.loads(sys.argv[1] or '{}').get('data') or {}
    print(data.get('id') or '')
except Exception:
    print('')
PY
)"
    if [[ -n "$script_id" ]]; then
      curl -sS -X DELETE "${BASE_URL}/test-scripts/${script_id}" \
        -H 'Accept: application/json' \
        -H "Authorization: Bearer ${TOKEN}" >/dev/null 2>&1 || true
    fi

    curl -sS -X DELETE "${BASE_URL}/test-cases/${tc_id}" \
      -H 'Accept: application/json' \
      -H "Authorization: Bearer ${TOKEN}" >/dev/null 2>&1 || true
  done

  curl -sS -X DELETE "${BASE_URL}/user-stories/${US_ID}" \
    -H 'Accept: application/json' \
    -H "Authorization: Bearer ${TOKEN}" >/dev/null 2>&1 || true
}

trap cleanup_resources EXIT

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-up)
      AUTO_UP=0
      shift
      ;;
    --no-cleanup)
      NO_CLEANUP=1
      shift
      ;;
    --timeout)
      TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1"
      ;;
  esac
done

log "Backend: ${BASE_URL}"
log "Frontend: ${FRONTEND_URL}"

if [[ "$AUTO_UP" -eq 1 ]]; then
  log "Starting services via docker compose..."
  docker compose up -d --wait --wait-timeout "$TIMEOUT_SECONDS"
fi

log "Waiting backend health..."
wait_for_backend || fail "Backend health endpoint not ready: ${BASE_URL}/actuator/health"

log "Waiting frontend availability..."
wait_for_frontend || fail "Frontend not reachable: ${FRONTEND_URL}"

log "[1/16] Login + auth"
api_call POST '/auth/login' '{"username":"admin","password":"admin123"}'
TOKEN="$(json_get 'data.accessToken' "$HTTP_BODY" || true)"
must_have "$TOKEN" 'Login token is empty.'

api_call GET '/auth/me' '' "$TOKEN"
api_call GET '/dashboard' '' "$TOKEN"

log "[3/16] User Story: create + update"
US_NUMBER="US-AUTO-$(date +%s)"
api_call POST '/user-stories' "{\"usNumber\":\"${US_NUMBER}\",\"title\":\"Auto Health US\",\"description\":\"health check us\",\"acceptanceCriteria\":\"api works\",\"priority\":\"HIGH\",\"sprint\":\"S1\",\"epic\":\"Health\",\"storyPoints\":\"3\"}" "$TOKEN"
US_ID="$(json_get 'data.id' "$HTTP_BODY" || true)"
must_have "$US_ID" 'US create failed: id empty.'

api_call PUT "/user-stories/${US_ID}" '{"title":"Auto Health US Updated","status":"READY","priority":"CRITICAL"}' "$TOKEN"

log "[4/16] User Story AI analyze"
api_call POST "/user-stories/${US_ID}/analyze" '{}' "$TOKEN"
ANALYSIS_SUMMARY="$(json_get 'data.analysisSummary' "$HTTP_BODY" || true)"
must_have "$ANALYSIS_SUMMARY" 'US analyze result is empty.'

log "[5/16] User Story AI generate test cases"
api_call POST "/user-stories/${US_ID}/generate-test-cases" '{"count":2}' "$TOKEN"
GEN_CASE_COUNT="$(json_len 'data' "$HTTP_BODY")"
[[ "$GEN_CASE_COUNT" -ge 1 ]] || fail 'Generated test case count < 1.'
AI_CASE_ID="$(json_get 'data[0].id' "$HTTP_BODY" || true)"
must_have "$AI_CASE_ID" 'Generated first test case id is empty.'

log "[6/16] Test Cases list + stats"
api_call GET '/test-cases?page=0&size=300' '' "$TOKEN"
api_call GET '/test-cases/stats' '' "$TOKEN"

log "[7/16] Test Case CRUD"
api_call POST '/test-cases' "{\"title\":\"Manual Health Case\",\"description\":\"manual create\",\"preconditions\":\"env ready\",\"testType\":\"API\",\"priority\":\"MEDIUM\",\"tags\":\"health,manual\",\"userStoryId\":${US_ID},\"steps\":[{\"stepOrder\":1,\"action\":\"Call endpoint\",\"expectedResult\":\"200\",\"testData\":\"\"}]}" "$TOKEN"
MANUAL_CASE_ID="$(json_get 'data.id' "$HTTP_BODY" || true)"
must_have "$MANUAL_CASE_ID" 'Manual test case id is empty.'

api_call PUT "/test-cases/${MANUAL_CASE_ID}" '{"title":"Manual Health Case Updated","status":"READY","priority":"HIGH"}' "$TOKEN"
api_call DELETE "/test-cases/${MANUAL_CASE_ID}" '' "$TOKEN"

log "[8/16] Test Scripts list"
api_call GET '/test-scripts?page=0&size=300' '' "$TOKEN"

log "[9/16] Test Script CRUD"
api_call POST '/test-scripts' "{\"name\":\"Health Script\",\"scriptType\":\"PLAYWRIGHT\",\"language\":\"JAVASCRIPT\",\"code\":\"console.log('health')\",\"config\":\"{}\",\"testCaseId\":${AI_CASE_ID}}" "$TOKEN"
SCRIPT_ID="$(json_get 'data.id' "$HTTP_BODY" || true)"
must_have "$SCRIPT_ID" 'Test script id is empty.'

api_call PUT "/test-scripts/${SCRIPT_ID}" '{"name":"Health Script Updated","status":"READY","code":"console.log(\"updated\")"}' "$TOKEN"

log "[10/16] AI Script generate"
api_call POST '/test-scripts/generate' "{\"testCaseId\":${AI_CASE_ID},\"scriptType\":\"PLAYWRIGHT\",\"language\":\"JAVASCRIPT\",\"targetUrl\":\"https://example.com\",\"additionalInstructions\":\"health check\"}" "$TOKEN"
GENERATED_CODE_LEN="$(json_len 'data.generatedCode' "$HTTP_BODY")"
[[ "$GENERATED_CODE_LEN" -gt 0 ]] || fail 'AI generated code is empty.'

api_call DELETE "/test-scripts/${SCRIPT_ID}" '' "$TOKEN"

log "[11/16] Executions list + stats"
api_call GET '/executions?page=0&size=300' '' "$TOKEN"
api_call GET '/executions/stats' '' "$TOKEN"

log "[12/16] Execution flow: create -> start -> complete"
api_call POST '/executions' "{\"testCaseId\":${AI_CASE_ID},\"browser\":\"chromium\",\"environment\":\"staging\"}" "$TOKEN"
EXEC1_ID="$(json_get 'data.id' "$HTTP_BODY" || true)"
must_have "$EXEC1_ID" 'Execution #1 id empty.'
api_call POST "/executions/${EXEC1_ID}/start" '{}' "$TOKEN"
api_call POST "/executions/${EXEC1_ID}/complete" '{"result":"PASS","logs":"completed by health check"}' "$TOKEN"

log "[13/16] Execution flow: create -> start -> fail"
api_call POST '/executions' "{\"testCaseId\":${AI_CASE_ID},\"browser\":\"chromium\",\"environment\":\"staging\"}" "$TOKEN"
EXEC2_ID="$(json_get 'data.id' "$HTTP_BODY" || true)"
must_have "$EXEC2_ID" 'Execution #2 id empty.'
api_call POST "/executions/${EXEC2_ID}/start" '{}' "$TOKEN"
api_call POST "/executions/${EXEC2_ID}/fail" '{"errorMessage":"health check fail path"}' "$TOKEN"

log "[14/16] Execution flow: create -> cancel"
api_call POST '/executions' "{\"testCaseId\":${AI_CASE_ID},\"browser\":\"chromium\",\"environment\":\"staging\"}" "$TOKEN"
EXEC3_ID="$(json_get 'data.id' "$HTTP_BODY" || true)"
must_have "$EXEC3_ID" 'Execution #3 id empty.'
api_call POST "/executions/${EXEC3_ID}/cancel" '{}' "$TOKEN"

log "[15/16] Report data verification"
api_call GET '/executions?page=0&size=300' '' "$TOKEN"
MATCH_COUNT="$(python3 - "$EXEC1_ID" "$EXEC2_ID" "$EXEC3_ID" "$HTTP_BODY" <<'PY'
import json
import sys
exec_ids = set(sys.argv[1:4])
obj = json.loads(sys.argv[4] or '{}')
items = obj.get('data', {}).get('content', [])
ids = {str(item.get('id')) for item in items if item.get('id') is not None}
print(len(exec_ids.intersection(ids)))
PY
)"
[[ "$MATCH_COUNT" -eq 3 ]] || fail 'Report data missing one or more created executions.'

log "[16/16] Frontend entry page"
curl -fsS "$FRONTEND_URL" >/dev/null

log 'All checks passed. Backend/Frontend/API button flows are healthy.'
