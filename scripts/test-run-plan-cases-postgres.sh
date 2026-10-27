#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# The shared environment stays private; the runner creates and drops its own DB/bucket.
source scripts/dev-runtime-env.sh
export NASUS_TEST_DATABASE_URL="${NASUS_TEST_DATABASE_URL:-$NASUS_DATABASE_URL}"
export NASUS_TEST_S3_ENDPOINT="${NASUS_TEST_S3_ENDPOINT:-$NASUS_S3_ENDPOINT}"
export NASUS_TEST_S3_ACCESS_KEY="${NASUS_TEST_S3_ACCESS_KEY:-$NASUS_S3_ACCESS_KEY}"
export NASUS_TEST_S3_SECRET_KEY="${NASUS_TEST_S3_SECRET_KEY:-$NASUS_S3_SECRET_KEY}"

exec ./.venv/bin/python scripts/test-api-postgres.py --minio \
  apps/api/tests/test_run_plan_case_work_postgres.py \
  apps/api/tests/test_run_plan_case_preparation_postgres.py \
  apps/api/tests/test_run_plan_case_job_postgres.py \
  apps/api/tests/test_run_plan_case_execution_postgres.py \
  apps/api/tests/test_http_fixture_preparation_postgres.py \
  apps/api/tests/test_http_fixture_preparation_cancel_postgres.py \
  -q "$@"
