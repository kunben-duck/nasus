import ast
from pathlib import Path

from apps.api.app.domain.quality_loop.run_plan import RUN_PLAN_TOOL, RUN_PLAN_PREVIEW_TOOL
from apps.api.app.application.platform.tool_catalog import core_tool_definitions, system_image_tool_definitions


ROOT = Path(__file__).resolve().parents[1]


def test_run_plan_domain_and_application_have_no_storage_runtime_or_foreign_repository_import():
    app = ROOT / "apps/api/app"
    for relative in ("domain/quality_loop/run_plan.py", "application/quality_loop/run_plans.py", "application/quality_loop/run_plan_inputs.py",
            "application/platform/run_plan_receipts.py", "application/platform/tool_receipt_access.py"):
        tree = ast.parse((app / relative).read_text())
        modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        assert not any(any(part in module.split(".") for part in
            ("infrastructure", "store", "sqlalchemy", "fastapi", "httpx", "boto3", "temporalio", "langgraph")) for module in modules)


def test_run_plan_http_only_previews_and_reads_and_canonical_prepare_requires_confirmation():
    tree = ast.parse((ROOT / "apps/api/app/interface/http/routers/run_plans.py").read_text())
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"prepare", "record", "commit", "execute"} for node in ast.walk(tree))
    catalog = {tool.tool_id: tool for tool in core_tool_definitions() + system_image_tool_definitions()}
    assert catalog[RUN_PLAN_TOOL].confirmation_mode == "user_confirm"
    assert catalog[RUN_PLAN_PREVIEW_TOOL].confirmation_mode == "none"


def test_run_plan_migration_is_frozen_ddl_and_does_not_invent_legacy_plans():
    source = (ROOT / "apps/api/migrations/versions/0101_run_plans.py").read_text()
    assert "op.create_table" in source and "__table__" not in source and "create_all" not in source
    assert "CREATE TRIGGER immutable_quality_run_plans" in source and "Cannot discard populated RunPlan history" in source
    assert "INSERT" not in source and "UPDATE" not in source.replace("BEFORE UPDATE OR DELETE", "")
