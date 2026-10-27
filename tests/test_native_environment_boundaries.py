import ast
from pathlib import Path

from apps.api.app.application.platform.tool_catalog import core_tool_definitions, system_image_tool_definitions
from apps.api.app.application.platform.tool_receipt_access import RESOURCE_RECEIPT_TOOLS
from apps.api.app.application.quality_loop.run_plan_environments import RUN_PLAN_ENVIRONMENT_QUERY_TOOL
from apps.api.app.domain.quality_loop.environment_observation_record import ENVIRONMENT_RECORD_TOOL, ENVIRONMENT_RECORD_QUERY_TOOL
from apps.api.app.domain.quality_loop.environment_health_record import HEALTH_RECORD_TOOL, HEALTH_RECORD_QUERY_TOOL


ROOT = Path(__file__).resolve().parents[1]


def test_native_environment_domain_and_use_case_are_independent_of_docker_orm_and_frameworks():
    for name in ("domain/quality_loop/native_environment.py", "domain/quality_loop/native_environment_health.py",
            "application/quality_loop/native_environment_ports.py", "application/quality_loop/run_plan_environment_health.py",
            "application/quality_loop/run_plan_environments.py"):
        tree = ast.parse((ROOT / "apps/api/app" / name).read_text())
        modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        assert not any(any(part in module.split(".") for part in
            ("infrastructure", "store", "sqlalchemy", "fastapi", "httpx", "boto3", "temporalio", "langgraph", "subprocess")) for module in modules)
        assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"build", "execute", "prepare", "invoke", "record", "commit", "deploy"} for node in ast.walk(tree))


def test_native_environment_only_exposes_exact_original_read_scope_and_protected_receipts():
    catalog = {tool.tool_id: tool for tool in core_tool_definitions() + system_image_tool_definitions()}
    definition = catalog[RUN_PLAN_ENVIRONMENT_QUERY_TOOL]
    assert definition.tool_kind == "query" and definition.confirmation_mode == "none"
    assert definition.required_context == ["project_id", "run_plan_id", "run_plan_artifact_hash", "build_binding_id", "build_binding_artifact_hash"]
    assert RUN_PLAN_ENVIRONMENT_QUERY_TOOL in RESOURCE_RECEIPT_TOOLS
    source = (ROOT / "apps/api/app/application/platform/run_plan_environment_receipts.py").read_text()
    assert ".inspect(" not in source and ".policy_digest(" not in source


def test_durable_environment_recording_has_independent_confirmation_and_no_framework_in_domain_or_application():
    catalog = {tool.tool_id: tool for tool in system_image_tool_definitions()}
    assert catalog[ENVIRONMENT_RECORD_TOOL].confirmation_mode == "user_confirm"
    assert catalog[ENVIRONMENT_RECORD_TOOL].tool_kind == "governance"
    assert catalog[ENVIRONMENT_RECORD_QUERY_TOOL].confirmation_mode == "none"
    assert {ENVIRONMENT_RECORD_TOOL, ENVIRONMENT_RECORD_QUERY_TOOL}.issubset(RESOURCE_RECEIPT_TOOLS)
    for name in ("domain/quality_loop/environment_observation_record.py", "application/quality_loop/environment_observation_records.py",
            "domain/quality_loop/environment_health_record.py", "application/quality_loop/environment_health_records.py"):
        tree = ast.parse((ROOT / "apps/api/app" / name).read_text())
        modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        assert not any(any(part in module.split(".") for part in
            ("infrastructure", "store", "sqlalchemy", "fastapi", "httpx", "boto3", "subprocess")) for module in modules)
    policy = (ROOT / "apps/api/app/application/platform/environment_record_receipts.py").read_text()
    assert ".inspect(" not in policy and ".record(" not in policy and ".policy_digest(" not in policy


def test_health_archival_has_independent_confirmation_and_protected_original_receipts():
    catalog = {tool.tool_id: tool for tool in system_image_tool_definitions()}
    assert catalog[HEALTH_RECORD_TOOL].confirmation_mode == "user_confirm"
    assert catalog[HEALTH_RECORD_TOOL].required_context == catalog[ENVIRONMENT_RECORD_TOOL].required_context
    assert catalog[HEALTH_RECORD_QUERY_TOOL].confirmation_mode == "none"
    assert {HEALTH_RECORD_TOOL, HEALTH_RECORD_QUERY_TOOL}.issubset(RESOURCE_RECEIPT_TOOLS)
    policy = (ROOT / "apps/api/app/application/platform/health_record_receipts.py").read_text()
    assert ".inspect(" not in policy and ".record(" not in policy and ".policy_digest(" not in policy
