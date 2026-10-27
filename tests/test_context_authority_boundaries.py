import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/api/app"


def test_historical_context_authority_domain_remains_adapter_free():
    source = (APP / "domain/system_image/context_authorities.py").read_text()
    for forbidden in ("sqlalchemy", "fastapi", "boto3", "infrastructure", "temporalio", "langgraph"):
        assert forbidden not in source
    assert 'payload["provenance"]["authority_pins"]' in source
    assert 'constraints[obj]["authority"] == pin' in source


def test_projection_and_event_replay_are_read_only_for_existing_context_authorities():
    source = (APP / "infrastructure/persistence/context_authority_projection_v1.py").read_text()
    for forbidden in ("artifact_ref", "session_scope", "Repository", "source_excerpt", "oracle"):
        assert forbidden not in source
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if node.func.value.id == "session":
                assert node.func.attr not in {"commit", "rollback", "update", "delete", "merge"}
    event_method = source.split("    def project_event(", 1)[1]
    assert "self.verify(session, context)" in event_method and "self.record(" not in event_method


def test_migration_enrolls_archives_but_never_guesses_authority_from_counts_or_heads():
    source = (ROOT / "apps/api/migrations/versions/0075_context_authorities.py").read_text()
    assert 'down_revision = "0074_authority_provenance"' in source and "Base.metadata" not in source
    for forbidden in ("MinIO", '["authority_pins"]', "AcceptanceRevisionRecord", "BusinessRuleRevisionRecord", "artifacts.read"):
        assert forbidden not in source
    assert "ContextAuthorityBackfillTargetRecord(" in source
    assert "BEFORE UPDATE OR DELETE" in source and "Cannot discard" in source
    app = (APP / "application/system_image/context_packs.py").read_text()
    for forbidden in ("sqlalchemy", "infrastructure", "session_scope"):
        assert forbidden not in app
    assert "archived_authority_pins(payload)" in app and "verify_authorities=False" in app


def test_portal_discovery_is_lazy_and_registration_uses_an_independent_canonical_confirmation():
    portal = ROOT / "apps/portal/src"
    api = (portal / "domains/system-image/contextAuthorityRegistrationApi.ts").read_text()
    hook = (portal / "domains/system-image/useContextAuthorityRegistration.ts").read_text()
    view = (portal / "routes/project/sections/knowledge/revisions/ContextAuthorityRegistrationQueue.tsx").read_text()
    assert "this.page(input.project_id, afterId)" in api
    assert "platformApi.invokeTool" in api and "platformApi.confirmToolInvocation(pending.id)" in api
    assert "waiting_confirmation" in api and "context_pack:${input.context_id}" in api
    assert "enabled: open && !!sessionId" in hook and "retry: false" in hook
    assert "!failed && !list.isFetching && !write.isPending" in hook
    assert "list.dataUpdatedAt" in hook and "submitted.current = true" in hook
    assert "disabled={!state.confirmed}" in view and "user.isFetching" in view
    assert "dangerouslySetInnerHTML" not in view


def test_canonical_discovery_remains_a_typed_read_only_application_port():
    handler = (APP / "application/platform/tool_handlers/context_packs.py").read_text()
    observer = (APP / "application/platform/tool_context_packs.py").read_text()
    assert "ContextAuthorityBackfillInput" in handler
    for source in (handler, observer):
        assert "CONTEXT_QUERY_INPUTS" in source and "context_authority_backfill" in source
        for forbidden in ("sqlalchemy", "infrastructure", "session_scope"):
            assert forbidden not in source
    query_branch = handler.split("            else:\n", 1)[1].split("            self.access", 1)[0]
    for source in (query_branch, observer):
        assert "self.application.receipt" in source
        assert "self.application.register_authorities" not in source and "self.application.compile" not in source
