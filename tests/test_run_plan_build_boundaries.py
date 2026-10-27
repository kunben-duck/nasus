import ast
from pathlib import Path

from apps.api.app.application.platform.tool_catalog import core_tool_definitions, system_image_tool_definitions
from apps.api.app.domain.quality_loop.run_plan_build import RUN_PLAN_BUILD_TOOL, RUN_PLAN_BUILD_PREVIEW_TOOL, RUN_PLAN_BUILD_QUERY_TOOL


ROOT = Path(__file__).resolve().parents[1]


def test_build_binding_domain_and_application_only_use_read_ports():
    for name in ("domain/quality_loop/run_plan_build.py", "application/quality_loop/run_plan_builds.py",
            "application/quality_loop/run_plan_build_inputs.py"):
        tree = ast.parse((ROOT / "apps/api/app" / name).read_text())
        modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        assert not any(any(part in module.split(".") for part in
            ("infrastructure", "store", "sqlalchemy", "fastapi", "httpx", "boto3", "temporalio", "langgraph")) for module in modules)
        assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"build", "execute", "prepare", "invoke"} for node in ast.walk(tree))


def test_build_binding_write_only_uses_independently_confirmed_canonical_tool():
    tree = ast.parse((ROOT / "apps/api/app/interface/http/routers/run_plans.py").read_text())
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"bind", "record", "commit", "execute"} for node in ast.walk(tree))
    catalog = {tool.tool_id: tool for tool in core_tool_definitions() + system_image_tool_definitions()}
    assert catalog[RUN_PLAN_BUILD_TOOL].confirmation_mode == "user_confirm"
    assert catalog[RUN_PLAN_BUILD_PREVIEW_TOOL].confirmation_mode == catalog[RUN_PLAN_BUILD_QUERY_TOOL].confirmation_mode == "none"
    assert catalog[RUN_PLAN_BUILD_TOOL].tool_kind == "governance"


def test_build_binding_migration_preserves_existing_plan_and_build_history():
    source = (ROOT / "apps/api/migrations/versions/0103_run_plan_build_bindings.py").read_text()
    assert "op.create_table" in source and "__table__" not in source and "create_all" not in source
    assert "Cannot discard populated RunPlan build binding history" in source
    assert "INSERT" not in source and "UPDATE" not in source.replace("BEFORE UPDATE OR DELETE", "")
    assert 'down_revision = "0102_native_builds"' in source
