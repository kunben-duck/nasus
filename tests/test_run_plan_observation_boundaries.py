import ast
from pathlib import Path

from apps.api.app.application.platform.tool_catalog import core_tool_definitions, system_image_tool_definitions
from apps.api.app.application.quality_loop.run_plan_observation_records import OBSERVATION_RECORD_TOOL, OBSERVATION_RECORD_QUERY_TOOL


ROOT = Path(__file__).resolve().parents[1] / "apps/api/app"


def test_observation_linkage_uses_ports_without_importing_a_runtime_or_foreign_repository():
    for relative in ("domain/quality_loop/run_plan_observations.py",
            "domain/quality_loop/run_plan_observation_record.py", "application/quality_loop/run_plan_observation_records.py",
            "application/quality_loop/run_plan_observations.py", "application/quality_loop/run_plan_observation_archives.py"):
        tree = ast.parse((ROOT / relative).read_text())
        modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        assert not any(any(part in module.split(".") for part in
            ("infrastructure", "sqlalchemy", "fastapi", "httpx", "boto3", "temporalio", "langgraph", "store")) for module in modules)
        assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"execute", "dispatch", "start_workflow", "invoke_tool", "send_message"} for node in ast.walk(tree))


def test_observation_record_write_has_no_direct_http_import_or_runner_bypass():
    tree = ast.parse((ROOT / "interface/http/routers/run_plans.py").read_text())
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"record", "archive", "execute", "dispatch"} for node in ast.walk(tree))
    catalog = {tool.tool_id: tool for tool in core_tool_definitions() + system_image_tool_definitions()}
    assert catalog[OBSERVATION_RECORD_TOOL].confirmation_mode == "user_confirm"
    assert catalog[OBSERVATION_RECORD_TOOL].tool_kind == "governance"
    assert catalog[OBSERVATION_RECORD_QUERY_TOOL].confirmation_mode == "none"


def test_observation_migration_adds_exact_original_parent_and_preserves_history():
    path = ROOT.parent / "migrations/versions/0104_run_plan_observations.py"
    source = path.read_text()
    assert 'down_revision = "0103_run_plan_build_bindings"' in source
    assert "Cannot discard populated RunPlan observation history" in source
    assert "__table__" not in source and "create_all" not in source and "INSERT" not in source
    assert "quality_run_plans.artifact_hash" in source and "quality_run_plans.manifest_id" in source
    assert "UPDATE" not in source.replace("BEFORE UPDATE OR DELETE", "")


def test_event_replay_verifies_in_the_read_session_without_write_side_projection():
    tree = ast.parse((ROOT / "infrastructure/persistence/event_outbox_repository.py").read_text())
    methods = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    for name in ("list_after", "_read_event", "_verify_run_plan_fact"):
        calls = {node.func.attr for node in ast.walk(methods[name])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        assert not calls & {"append", "add", "flush", "project_event", "backfill", "record", "dispatch"}
    assert "_verify_run_plan_fact" in {node.func.attr for node in ast.walk(methods["_read_event"])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    read = next(node for node in ast.walk(methods["list_after"]) if isinstance(node, ast.With))
    assert any(isinstance(node, ast.Return) for node in ast.walk(read))
