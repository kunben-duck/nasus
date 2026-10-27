"""Exercise release shell functions without connecting to operator services."""
from pathlib import Path
import os
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def gate(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    source = (ROOT / "scripts/verify-v1-release.sh").read_text()
    # Execute the real definitions, not the expensive gate or its EXIT cleanup.
    definitions = scripts / "gate-definitions.sh"
    definitions.write_text(source.split("trap cleanup EXIT", 1)[0])
    (scripts / "dev-runtime-env.sh").write_text("""
export NASUS_DATABASE_URL="${NASUS_DATABASE_URL:-postgresql+psycopg://test@127.0.0.1:${POSTGRES_PORT:-15432}/operator}"
export NASUS_S3_ENDPOINT="${NASUS_S3_ENDPOINT:-http://127.0.0.1:${MINIO_API_PORT:-19000}}"
export NASUS_S3_ACCESS_KEY="${NASUS_S3_ACCESS_KEY:-test-access}"
export NASUS_S3_SECRET_KEY="${NASUS_S3_SECRET_KEY:-test-secret}"
""")
    python = tmp_path / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("""#!/usr/bin/env bash
printf '%s\\n' "$NASUS_TEST_DATABASE_URL" "$NASUS_TEST_S3_ENDPOINT" "$NASUS_TEST_S3_ACCESS_KEY" "$NASUS_TEST_S3_SECRET_KEY" "$*"
""")
    python.chmod(0o700)
    docker = scripts / "verify-docker-stack.sh"
    docker.write_text("""#!/usr/bin/env bash
printf '%s\\n' "$POSTGRES_PORT" "$MINIO_API_PORT" "$MINIO_CONSOLE_PORT" "$NASUS_API_PORT" "$TEMPORAL_PORT" "$*" > "$NASUS_TEST_CAPTURE_FILE"
""")
    docker.chmod(0o700)
    env = {key: value for key, value in os.environ.items() if not key.startswith("NASUS_")}
    for key in ("POSTGRES_PORT", "MINIO_API_PORT", "MINIO_CONSOLE_PORT", "TEMPORAL_PORT"):
        env.pop(key, None)
    env.update({
        "NASUS_RELEASE_POSTGRES_PORT": "25432",
        "NASUS_RELEASE_MINIO_API_PORT": "29000",
        "NASUS_RELEASE_MINIO_CONSOLE_PORT": "29001",
        "NASUS_RELEASE_API_PORT": "28000",
        "NASUS_RELEASE_TEMPORAL_PORT": "27233",
        "NASUS_TEST_CAPTURE_FILE": str(tmp_path / "cleanup-output"),
    })
    return definitions, env


def run_function(gate, function, overrides=None):
    definitions, env = gate
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; "$2"', "release-test", str(definitions), function],
        env={**env, **(overrides or {})}, capture_output=True, text=True, check=True,
    )
    return result.stdout.splitlines()


@pytest.mark.parametrize("operator_ports", [{}, {"POSTGRES_PORT": "35432", "MINIO_API_PORT": "39000"}])
def test_backend_uses_operator_services_not_unstarted_compose_ports(gate, operator_ports):
    lines = run_function(gate, "run_backend_gate", operator_ports)
    assert lines[:4] == [
        f"postgresql+psycopg://test@127.0.0.1:{operator_ports.get('POSTGRES_PORT', '15432')}/operator",
        f"http://127.0.0.1:{operator_ports.get('MINIO_API_PORT', '19000')}",
        "test-access", "test-secret",
    ]
    assert "test-api-postgres.py --minio apps/api/tests" in lines[4]
    assert "tests/test_docker_stack_contract.py" in lines[4]


def test_backend_preserves_explicit_test_server_and_private_storage(gate):
    lines = run_function(gate, "run_backend_gate", {
        "NASUS_RELEASE_TEST_DATABASE_URL": "postgresql+psycopg://test@127.0.0.1:45432/release_tests",
        "NASUS_TEST_DATABASE_URL": "postgresql+psycopg://test@127.0.0.1:45433/other_tests",
        "NASUS_TEST_S3_ENDPOINT": "http://127.0.0.1:49000",
        "NASUS_TEST_S3_ACCESS_KEY": "private-access",
        "NASUS_TEST_S3_SECRET_KEY": "private-secret",
    })
    assert lines[:4] == [
        "postgresql+psycopg://test@127.0.0.1:45432/release_tests",
        "http://127.0.0.1:49000", "private-access", "private-secret",
    ]


def test_cleanup_keeps_exact_release_stack_ports(gate):
    assert run_function(gate, "cleanup") == []
    assert Path(gate[1]["NASUS_TEST_CAPTURE_FILE"]).read_text().splitlines() == [
        "25432", "29000", "29001", "28000", "27233", "--down",
    ]
