import ast
from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "apps/api/app"


def test_impact_uses_application_ports_and_domain_has_no_runtime_or_persistence():
    for relative in ("domain/system_image/derivation_impact.py", "application/system_image/context_change_impact.py",
                     "application/quality_loop/context_dependencies.py"):
        source = (APP / relative).read_text()
        for forbidden in ("sqlalchemy", "fastapi", "boto3", "ApplicationStore", "infrastructure.", "temporalio", "langgraph"):
            assert forbidden not in source
    image_application = (APP / "application/system_image/context_change_impact.py").read_text()
    assert ".quality.read(" in image_application and ".deltas.compare(" in image_application
    assert ".repository" not in image_application
    quality = (APP / "application/quality_loop/context_dependencies.py").read_text()
    assert ".scopes.read(" in quality and ".results.read(" in quality and ".mappings.read(" in quality


def test_dependency_inventory_is_scoped_read_only_and_uses_one_bounded_union():
    source = (APP / "infrastructure/persistence/context_dependency_inventory.py").read_text()
    assert "union_all(scopes, generations, mappings)" in source
    assert "Scope.project_id == project_id, Scope.context_id == context_id" in source
    assert ".limit(MAX_DEPENDENCIES)" in source and "DerivationImpactTooLarge" in source
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"add", "add_all", "update", "delete", "merge", "commit"}


def test_impact_receipt_is_body_free_and_replay_uses_fixed_inventory():
    source = (APP / "application/system_image/image_query_models.py").read_text()
    receipt = next(node for node in ast.parse(source).body
                   if isinstance(node, ast.ClassDef) and node.name == "ImageContextImpactReceipt")
    fields = {node.target.id for node in receipt.body if isinstance(node, ast.AnnAssign)}
    assert {"dependency_pins", "graph_hash", "delta_hash", "invalidation_applied", "impact_complete"} <= fields
    assert not fields & {"dependencies", "paths", "content", "artifact_ref", "source_fields", "oracle", "title"}
    queries = (APP / "application/system_image/image_query_tools.py").read_text()
    assert "pinned=pins" in queries and "ImageContextImpactReceipt" in queries
    handler = (APP / "application/platform/tool_handlers/image_queries.py").read_text()
    assert '"query.system_image.context.change_impact": ImageContextImpactInput' in handler
    interface = (APP / "interface/http/routers/context_change_impact.py").read_text()
    assert "application.read(" in interface and "private, no-store" in interface
    assert ".repository" not in interface and "session_scope" not in interface
