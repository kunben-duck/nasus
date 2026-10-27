import ast
from pathlib import Path
import re

from apps.api.app.infrastructure.runner.owned_target_environment import CONTAINER_FORMAT, NETWORK_FORMAT


ROOT = Path(__file__).resolve().parents[1]


def test_owned_runner_application_port_does_not_import_execution_infrastructure():
    path = ROOT / "apps/api/app/application/quality_loop/runner_port.py"
    tree = ast.parse(path.read_text())
    modules = [item.module or "" for item in ast.walk(tree) if isinstance(item, ast.ImportFrom)]
    modules += [alias.name for item in ast.walk(tree) if isinstance(item, ast.Import) for alias in item.names]
    assert not any(any(part in module.split(".") for part in
        ("infrastructure", "sqlalchemy", "fastapi", "httpx", "subprocess", "temporalio", "langgraph")) for module in modules)


def test_node_and_python_inspect_exactly_the_same_credential_free_metadata():
    source = (ROOT / "apps/runner/src/owned-http-cohort.mjs").read_text()
    for key, value in (("OWNED_CONTAINER_FORMAT", CONTAINER_FORMAT), ("OWNED_NETWORK_FORMAT", NETWORK_FORMAT)):
        assert re.search(r"export const " + key + r" = '([^']+)'", source).group(1) == value
    assert ".Config.Env" not in CONTAINER_FORMAT and "{{json .Args}}" not in CONTAINER_FORMAT


def test_public_http_runner_cannot_select_the_owned_docker_transport():
    server = (ROOT / "apps/runner/src/server.mjs").read_text()
    job = (ROOT / "apps/runner/src/http-job.mjs").read_text()
    assert "owned-http" not in server and "docker-http-transport" not in server
    assert "owned-http" not in job and "container_id" not in job and "registry_path" not in job
    cli = (ROOT / "apps/runner/src/owned-http-cli.mjs").read_text()
    assert "--execute-owned-target-http" in cli and "wire_body_base64" in cli


def test_actual_exweb_probe_uses_the_application_owned_port_not_caller_selected_cli_ids():
    source = (ROOT / "scripts/verify-exweb-runtime.py").read_text()
    assert "adapter.execute_owned_http(job" in source
    assert "ConfiguredOwnedTargetEnvironments(registry_path=str(registry))" in source
    assert "inventory_hash=inventory.inventory_hash" in source
    assert "verify-exweb-http-runner.mjs" not in source
    assert "nasus_runplan_verified\": False" in source
