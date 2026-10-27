import ast
from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "apps/api/app"


def test_reverse_root_discovery_stays_on_application_ports_and_immutable_domain_pins():
    for relative in ("domain/system_image/source_context_roots.py", "application/system_image/source_context_roots.py"):
        source = (APP / relative).read_text()
        for forbidden in ("sqlalchemy", "fastapi", "boto3", "ApplicationStore", "infrastructure.", "temporalio", "langgraph"):
            assert forbidden not in source
    source = (APP / "application/system_image/source_context_roots.py").read_text()
    assert ".contexts.read(" in source and ".images.frozen_snapshot(" in source and ".deltas.compare(" in source
    assert "selected_hits" not in source and '"source_members"' in source
    assert "pinned is None else pinned" in source


def test_reverse_inventory_uses_one_snapshot_with_total_and_project_source_joins_no_business_writes():
    source = (APP / "infrastructure/persistence/source_context_root_inventory.py").read_text()
    assert source.count("session.execute(") == 1 and "total.outerjoin(page, true())" in source
    assert "Context.project_id == project_id" in source and "Member.source_revision_id == source_revision_id" in source
    assert "Context.project_id == Image.project_id" in source and "Image.project_id == Member.project_id" in source
    assert "hidden.binding_id.not_in(binding_ids)" in source and "~inaccessible_source" in source
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"add", "add_all", "update", "delete", "merge", "commit"}


def test_source_root_receipt_is_strict_body_free_and_the_interface_only_delegates():
    source = (APP / "application/system_image/image_query_models.py").read_text()
    tree = ast.parse(source)
    for name in ("SourceContextRootPin", "SourceContextRootsReceipt"):
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
        fields = {node.target.id for node in cls.body if isinstance(node, ast.AnnAssign)}
        assert not fields & {"paths", "content", "artifact_ref", "source_fields", "oracle", "title"}
    handler = (APP / "application/platform/tool_handlers/image_queries.py").read_text()
    assert '"query.system_image.sources.context_roots": SourceContextRootsInput' in handler
    queries = (APP / "application/system_image/image_query_tools.py").read_text()
    assert "source_context_roots.read(**receipt.request.model_dump(), pinned=page," in queries
    assert "pinned_scope_fingerprint=receipt.source_scope_fingerprint" in queries
    interface = (APP / "interface/http/routers/context_change_impact.py").read_text()
    assert '"/v1/projects/{project_id}/system-image/source-context-roots"' in interface
    assert ".repository" not in interface and "session_scope" not in interface
    replay = (APP / "interface/http/routers/image_revisions.py").read_text()
    assert "response_model=ImageQueryObservation" in replay
