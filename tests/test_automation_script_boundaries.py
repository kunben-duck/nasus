"""The native script/review path cannot bypass context ports or canonical tools."""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "apps" / "api" / "app"


def imports(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield node.module or ""


def test_script_domain_has_no_runtime_storage_or_provider_dependency():
    for name in ("automation_scripts.py", "automation_script_review.py"):
        modules = tuple(imports(ROOT / "domain" / "quality_loop" / name))
        assert not any(any(part in module.split(".") for part in
            ("sqlalchemy", "infrastructure", "application", "fastapi", "langgraph", "temporalio", "httpx", "boto3"))
            for module in modules), modules


def test_script_applications_consume_ports_not_foreign_repositories():
    for name in ("automation_inputs.py", "automation_script_generation.py", "automation_script_reviews.py"):
        modules = tuple(imports(ROOT / "application" / "quality_loop" / name))
        assert not any("infrastructure" in module.split(".") or "store" in module.split(".")
            or module.startswith(("sqlalchemy", "fastapi", "httpx", "boto3")) for module in modules), modules


def test_native_script_http_surface_has_no_direct_write_endpoint():
    path = ROOT / "interface" / "http" / "routers" / "automation_scripts.py"
    tree = ast.parse(path.read_text())
    routes = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                    if isinstance(decorator.func.value, ast.Name) and decorator.func.value.id == "router":
                        routes.append((decorator.func.attr, decorator.args[0].value))
    assert routes and all(method == "get" or method == "post" and route.endswith("automation-script-previews")
        for method, route in routes), routes
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"execute", "review", "record", "commit"} for node in ast.walk(tree))


def test_native_script_tools_are_registered_with_explicit_confirmation():
    from apps.api.app.application.platform.tool_catalog import core_tool_definitions, system_image_tool_definitions
    from apps.api.app.domain.quality_loop.automation_script_review import SCRIPT_REVIEW_TOOL, SCRIPT_REVIEW_QUERY_TOOL
    from apps.api.app.application.quality_loop.automation_script_inputs import SCRIPT_TOOL, SCRIPT_PREVIEW_TOOL, SCRIPT_HISTORY_TOOL
    catalog = {tool.tool_id: tool for tool in core_tool_definitions() + system_image_tool_definitions()}
    for ident in (SCRIPT_TOOL, SCRIPT_REVIEW_TOOL):
        assert catalog[ident].confirmation_mode == "user_confirm"
    for ident in (SCRIPT_PREVIEW_TOOL, SCRIPT_REVIEW_QUERY_TOOL, SCRIPT_HISTORY_TOOL):
        assert catalog[ident].confirmation_mode == "none"
