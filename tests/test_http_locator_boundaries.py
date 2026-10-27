import ast
from pathlib import Path

from apps.api.app.application.platform.tool_catalog import core_tool_definitions, system_image_tool_definitions
from apps.api.app.application.quality_loop.run_plan_locators import RUN_PLAN_LOCATOR_QUERY_TOOL


ROOT = Path(__file__).resolve().parents[1]


def test_locator_policy_and_use_case_depend_on_ports_not_storage_parser_or_runtime():
    for relative in ("domain/quality_loop/http_locator_evidence.py", "application/quality_loop/run_plan_locators.py",
            "domain/quality_loop/http_locator_record.py", "application/quality_loop/http_locator_records.py",
            "application/platform/http_locator_record_receipts.py", "application/platform/tool_handlers/http_locator_records.py",
            "application/platform/run_plan_locator_receipts.py", "application/platform/tool_handlers/run_plan_locators.py"):
        tree = ast.parse((ROOT / "apps/api/app" / relative).read_text())
        modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        assert not any(any(part in module.split(".") for part in (
            "infrastructure", "store", "sqlalchemy", "fastapi", "httpx", "boto3", "tree_sitter", "temporalio", "langgraph")) for module in modules)


def test_locator_tool_is_readonly_and_original_receipts_are_required():
    tools = {tool.tool_id: tool for tool in core_tool_definitions() + system_image_tool_definitions()}
    assert tools[RUN_PLAN_LOCATOR_QUERY_TOOL].confirmation_mode == "none"
    assert tools[RUN_PLAN_LOCATOR_QUERY_TOOL].required_context == ["project_id", "run_plan_id", "run_plan_artifact_hash"]
    source = (ROOT / "apps/api/app/application/platform/tool_receipt_access.py").read_text()
    assert "RUN_PLAN_LOCATOR_QUERY_TOOL" in source
    router = ast.parse((ROOT / "apps/api/app/interface/http/routers/run_plans.py").read_text())
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"prepare", "record", "commit", "execute"} for node in ast.walk(router))


def test_http_locator_dependency_is_exposed_by_the_composed_container():
    tree = ast.parse((ROOT / "apps/api/app/bootstrap/container.py").read_text())
    container = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ApplicationContainer")
    assert any(isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        and node.target.id == "run_plan_locators" for node in container.body)
    assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ApplicationContainer"
        and any(keyword.arg == "run_plan_locators" and isinstance(keyword.value, ast.Attribute)
            and keyword.value.attr == "run_plan_locators" for keyword in node.keywords) for node in ast.walk(tree))


def test_independent_locator_record_is_confirmed_and_all_original_receipts_fail_closed():
    from apps.api.app.domain.quality_loop.http_locator_record import LOCATOR_RECORD_TOOL, LOCATOR_RECORD_QUERY_TOOL
    from apps.api.app.application.platform.tool_receipt_access import RESOURCE_RECEIPT_TOOLS
    tools = {tool.tool_id: tool for tool in core_tool_definitions() + system_image_tool_definitions()}
    assert tools[LOCATOR_RECORD_TOOL].confirmation_mode == "user_confirm"
    assert tools[LOCATOR_RECORD_TOOL].required_context == ["project_id", "run_plan_id", "run_plan_artifact_hash"]
    assert tools[LOCATOR_RECORD_QUERY_TOOL].confirmation_mode == "none"
    assert {LOCATOR_RECORD_TOOL, LOCATOR_RECORD_QUERY_TOOL} <= RESOURCE_RECEIPT_TOOLS
    tree = ast.parse((ROOT / "apps/api/app/bootstrap/container.py").read_text())
    assert any(isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        and node.target.id == "http_locator_records" for node in ast.walk(tree))
    assert any(isinstance(node, ast.keyword) and node.arg == "http_locator_records" for node in ast.walk(tree))
