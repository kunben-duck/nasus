"""Exercise release shell functions without connecting to operator services."""
from pathlib import Path
import importlib.util
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
export EXWEB_CANONICAL_HANDOFF_REPORT="${EXWEB_CANONICAL_HANDOFF_REPORT:-should-not-write.json}"
""")
    python = tmp_path / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("""#!/usr/bin/env bash
printf '%s\\n' "$NASUS_TEST_DATABASE_URL" "$NASUS_TEST_S3_ENDPOINT" "$NASUS_TEST_S3_ACCESS_KEY" "$NASUS_TEST_S3_SECRET_KEY" "$*"
printf 'pytest_options=%s\\npytest_plugins=%s\\nexweb_execute=%s\\nexweb_report=%s\\n' \\
  "${PYTEST_ADDOPTS+x}" "${PYTEST_PLUGINS+x}" "${EXWEB_EXECUTE_REVIEWED_NATIVE_BUILD+x}" "${EXWEB_CANONICAL_HANDOFF_REPORT+x}"
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
    command, separator, suites = lines[4].partition(" --minio ")
    assert command.endswith("test-api-postgres.py") and separator
    assert suites.split() == ["apps/api/tests", "tests/test_docker_stack_contract.py", "tests/test_ddd_boundaries.py",
        "tests/test_isolated_test_storage.py", "tests/test_release_gate_environment.py", "-q"]


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


def test_backend_ignores_inherited_test_filters_and_target_execution_opt_in(gate):
    lines = run_function(gate, "run_backend_gate", {
        "PYTEST_ADDOPTS": "-k excluded_all --collect-only",
        "PYTEST_PLUGINS": "filtered_collection",
        "EXWEB_EXECUTE_REVIEWED_NATIVE_BUILD": "1",
    })
    assert lines[5:] == ["pytest_options=", "pytest_plugins=", "exweb_execute=", "exweb_report="]


def test_parallel_backend_gate_keeps_the_same_suite_and_ignores_operator_filters(gate):
    serial = run_function(gate, "run_backend_gate")[4].split(" --minio ")[1].removesuffix(" -q")
    lines = run_function(gate, "run_backend_gate", {"NASUS_RELEASE_BACKEND_WORKERS": "3", "PYTEST_ADDOPTS": "-k none"})
    assert lines[4].endswith(f"test-api-postgres-shards.py --workers 3 {serial}")
    assert lines[5:] == ["pytest_options=", "pytest_plugins=", "exweb_execute=", "exweb_report="]


@pytest.fixture
def backend_shards():
    spec = importlib.util.spec_from_file_location("release_backend_shards", ROOT / "scripts/test-api-postgres-shards.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backend_partition_is_deterministic_disjoint_and_complete(backend_shards):
    counts = backend_shards.inventory("\n".join([
        "apps/api/tests/test_b.py::test_b[hello::world]", "apps/api/tests/test_b.py::test_c", "tests/test_a.py::test_a",
        "tests/test_c.py::test_d", "tests/test_d.py::test_e", "5 tests collected in 0.01s",
    ]))
    groups = backend_shards.partitions(counts, 3)
    assert groups == backend_shards.partitions(dict(reversed(list(counts.items()))), 3)
    assert sum(groups, type(counts)()) == counts
    assert sum(map(len, groups)) == len(counts)
    assert sorted(sum(group.values()) for group in groups) == [1, 2, 2]


@pytest.mark.parametrize("collection", ["2 tests collected in 0.01s", "1/2 tests collected in 0.01s", "1 test collected in 0.01s"])
def test_backend_inventory_rejects_missing_filtered_and_duplicate_collection(backend_shards, collection):
    node = "tests/test_one.py::test_a\n"
    with pytest.raises(ValueError, match="collection"):
        backend_shards.inventory(node + (node if collection.startswith("1 test") else "") + collection)


def test_backend_junit_rejects_missing_cases_and_failures(backend_shards, tmp_path):
    path = tmp_path / "report.xml"
    path.write_text('<testsuite><testcase file="tests/test_a.py"/></testsuite>')
    backend_shards.verify_junit(path, {"tests/test_a.py": 1})
    with pytest.raises(ValueError, match="inventory"):
        backend_shards.verify_junit(path, {"tests/test_a.py": 2})
    path.write_text('<testsuite><testcase file="tests/test_a.py"><failure/></testcase></testsuite>')
    with pytest.raises(ValueError, match="failures"):
        backend_shards.verify_junit(path, {"tests/test_a.py": 1})


def test_cleanup_keeps_exact_release_stack_ports(gate):
    assert run_function(gate, "cleanup") == []
    assert Path(gate[1]["NASUS_TEST_CAPTURE_FILE"]).read_text().splitlines() == [
        "25432", "29000", "29001", "28000", "27233", "--down",
    ]
