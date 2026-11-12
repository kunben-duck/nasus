#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source scripts/dev-runtime-env.sh

REPO="${1:-$ROOT/.nasus/validation/realworld-django-ninja}"
COMMIT="87dd078c883a046f5ff20269df2fb004d8b5f83f"
git -C "$REPO" cat-file -e "$COMMIT^{commit}"
export M1_REALWORLD_REPOSITORY="$(cd "$REPO" && pwd)"
export NASUS_TEST_DATABASE_URL="${NASUS_TEST_DATABASE_URL:-$NASUS_DATABASE_URL}"
export NASUS_TEST_S3_ENDPOINT="${NASUS_TEST_S3_ENDPOINT:-$NASUS_S3_ENDPOINT}"
export NASUS_TEST_S3_ACCESS_KEY="${NASUS_TEST_S3_ACCESS_KEY:-$NASUS_S3_ACCESS_KEY}"
export NASUS_TEST_S3_SECRET_KEY="${NASUS_TEST_S3_SECRET_KEY:-$NASUS_S3_SECRET_KEY}"
OUTPUT="$ROOT/output/realworld/m1-$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$OUTPUT"
export M1_ACCEPTANCE_REPORT="$OUTPUT/report.json"

# The harness owns a disposable PG database and MinIO bucket, not development data.
./.venv/bin/python scripts/test-api-postgres.py --minio \
  'apps/api/tests/test_delivery_dialogue_api.py::test_chat_project_to_reviewed_image_and_explicit_iteration[langgraph_postgres]' \
  -q --junitxml="$OUTPUT/junit.xml" 2>&1 | tee "$OUTPUT/verification.log"
test -s "$M1_ACCEPTANCE_REPORT"
printf '\nM1 source/image/iteration evidence: %s\nNot a live-model or M2-M5 quality-loop verification.\n' "$M1_ACCEPTANCE_REPORT"
