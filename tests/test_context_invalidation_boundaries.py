from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "apps/api/app"


def test_invalidation_domain_application_and_interface_keep_dependency_direction():
    for name in ("domain/system_image/context_invalidation.py", "application/system_image/context_invalidations.py"):
        source = (APP / name).read_text()
        for forbidden in ("sqlalchemy", "fastapi", "boto3", "ApplicationStore", "infrastructure.", "langgraph", "temporalio"):
            assert forbidden not in source
    source = (APP / "application/system_image/context_invalidations.py").read_text()
    assert "self.impacts.read(" in source and "require_current=require_current" in source
    assert "scope_revision" not in source and "quality_loop" not in source


def test_current_consumers_use_the_context_port_and_never_rewrite_history():
    context = (APP / "application/system_image/context_packs.py").read_text()
    assert "self.repository.stale_state(" in context and '"source_change_invalidated"' in context
    for name in ("test_design_scopes.py", "test_design_results.py", "test_design_mappings.py", "mapping_part_staging.py"):
        source = (APP / "application/quality_loop" / name).read_text()
        assert '"stale"' in source or '"scope_current"' in source
        assert "context_invalidation_models" not in source
    repo = (APP / "infrastructure/persistence/context_invalidation_repository.py").read_text()
    assert "require_current()" in repo and "fresh=True" in repo and "_lock(session, request.project_id)" in repo
    assert "EventOutboxRepository().append(" in repo and 'event_type="system_image.context.invalidated"' in repo
    assert ".update(" not in repo and ".delete(" not in repo


def test_canonical_command_and_migration_are_explicit_and_append_only():
    handler = (APP / "application/platform/tool_handlers/context_invalidations.py").read_text()
    assert "self.application.invalidate" in handler and "object_refs=" in handler and "str(exc)" not in handler
    migration = (APP.parent / "migrations/versions/0067_context_invalidations.py").read_text()
    assert 'down_revision = "0066_mapping_part_staging"' in migration
    assert "BEFORE UPDATE OR DELETE" in migration and "cannot downgrade while context invalidations exist" in migration
    assert "system_image_context_invalidation_nodes" in migration and "system_image_context_invalidation_edges" in migration
