"""Keep revision deltas on the existing governed, body-free observation path."""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/api/app"


def test_source_delta_layers_do_not_depend_on_store_orm_or_external_providers():
    for path in (APP / "domain/system_image/source_delta.py", APP / "application/system_image/source_deltas.py"):
        source = path.read_text()
        for forbidden in ("sqlalchemy", "fastapi", "boto3", "ApplicationStore", "codebase_memory", "infrastructure", "langgraph", "temporalio"):
            assert forbidden not in source
    interface = (APP / "interface/http/routers/source_deltas.py").read_text()
    assert "application.read(" in interface and "except PlatformApplicationError:" in interface
    for forbidden in (".repository", ".reader", "session_scope", "ApplicationStore"):
        assert forbidden not in interface


def test_delta_persistence_reader_has_no_write_operations():
    tree = ast.parse((APP / "infrastructure/persistence/source_delta_repository.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"add", "add_all", "delete", "update", "merge", "commit", "bulk_save_objects"}


def test_delta_receipt_is_metadata_only_and_uses_canonical_image_observation():
    models = ast.parse((APP / "application/system_image/image_query_models.py").read_text())
    receipt = next(node for node in models.body if isinstance(node, ast.ClassDef) and node.name == "ImageSourceDeltaReceipt")
    fields = {node.target.id for node in receipt.body if isinstance(node, ast.AnnAssign)}
    assert fields.isdisjoint({"items", "paths", "content", "manifest_ref", "source_uri", "before_path", "after_path", "api_key"})
    assert {"request", "delta_hash", "counts", "impact_complete", "publication_authorized"} <= fields
    handler = (APP / "application/platform/tool_handlers/image_queries.py").read_text()
    assert '"query.system_image.sources.delta": ImageSourceDeltaInput' in handler
    assert "image_query=receipt" in handler
    registry = (APP / "application/platform/tool_handlers/registry.py").read_text()
    assert "for tool_id in IMAGE_QUERY_INPUTS:" in registry
    observer = (APP / "application/platform/tool_images.py").read_text()
    assert "self.images.expand(receipt)" in observer
    assert "self.access.require_invocation_project_scope(invocation)" in observer
