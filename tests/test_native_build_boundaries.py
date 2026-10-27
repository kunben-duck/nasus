import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "apps/api/app"


def test_native_build_ports_and_values_do_not_import_execution_or_persistence():
    for name in ("domain/shared/native_build_source.py", "domain/quality_loop/native_build.py",
                 "application/system_image/native_build_sources.py", "application/quality_loop/native_build_ports.py",
                 "application/quality_loop/native_builds.py", "application/quality_loop/native_build_inputs.py",
                 "application/quality_loop/native_build_jobs.py"):
        tree = ast.parse((ROOT / name).read_text())
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        assert not any(any(part in module.split(".") for part in ("infrastructure", "sqlalchemy", "fastapi",
            "boto3", "subprocess", "temporalio", "langgraph", "store")) for module in imports)


def test_native_build_execution_remains_an_application_port_consumer():
    tree = ast.parse((ROOT / "application/quality_loop/native_build_execution.py").read_text())
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not any(any(part in module.split(".") for part in ("infrastructure", "sqlalchemy", "fastapi",
        "boto3", "subprocess", "temporalio", "langgraph", "store")) for module in imports)


def test_native_build_adapter_has_no_public_http_or_tool_dispatch():
    for folder in (ROOT / "interface/http", ROOT / "application/platform"):
        assert not any("OfflineMavenNativeBuild" in path.read_text() for path in folder.rglob("*.py"))


def test_native_build_commands_have_independent_confirmation_and_application_worker_wiring():
    from apps.api.app.application.platform.tool_catalog import core_tool_definitions
    from apps.api.app.application.quality_loop.native_build_inputs import (
        NATIVE_BUILD_TOOL, NATIVE_BUILD_PREVIEW_TOOL, NATIVE_BUILD_QUERY_TOOL, NATIVE_BUILD_CANCEL_TOOL,
    )
    catalog = {tool.tool_id: tool for tool in core_tool_definitions()}
    assert catalog[NATIVE_BUILD_TOOL].confirmation_mode == catalog[NATIVE_BUILD_CANCEL_TOOL].confirmation_mode == "user_confirm"
    assert catalog[NATIVE_BUILD_PREVIEW_TOOL].confirmation_mode == catalog[NATIVE_BUILD_QUERY_TOOL].confirmation_mode == "none"
    handler = (ROOT / "application/platform/tool_handlers/native_builds.py").read_text()
    assert "await self.jobs.dispatch" in handler and "await self.jobs.cancel" in handler
    assert "builder.build" not in handler and "artifacts.put" not in handler
    worker = (ROOT / "infrastructure/workflow/agent_goal_workflow_worker.py").read_text()
    assert "workflows=[NasusNativeBuildWorkflow]" in worker and "reconcile_native_builds(native_runtime)" in worker


def test_native_build_migration_has_frozen_ddl_and_preserves_uncertain_legacy_history():
    source = (ROOT.parent / "migrations/versions/0102_native_builds.py").read_text()
    assert "op.create_table" in source and "__table__" not in source and "create_all" not in source
    assert "nasus_reject_image_revision_mutation" in source and "Cannot discard populated native build history" in source
    assert "INSERT" not in source and "UPDATE" not in source.replace("BEFORE UPDATE OR DELETE", "")
