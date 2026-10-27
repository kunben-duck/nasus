import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from apps.api.app.application.agent.observation_receipts import observation_receipt_fingerprint
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.tool_catalog import system_image_tool_definitions
from apps.api.app.application.platform.tool_context_packs import ToolContextPackObservationApplicationService
from apps.api.app.application.platform.tool_handlers.context_packs import ContextPackToolHandler
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.system_image.context_packs import ContextPackApplicationService
from apps.api.app.application.system_image.context_pack_inputs import (
    CONTEXT_AUTHORITY_BACKFILL_TOOL, ContextAuthorityBackfillInput, ContextAuthorityBackfillReceipt,
)
from apps.api.app.domain.platform.rbac import ToolRBAC
from apps.api.app.domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest


def service(role="qa_lead"):
    metadata = {ident: {"context_id": ident, "project_id": "project", "artifact_hash": "sha256:" + ident * 64,
        "image_revision_id": "image", "image_artifact_hash": "sha256:" + "f" * 64} for ident in ("a", "b", "c")}
    scope = SimpleNamespace(effective_project_role=role)
    auth = Mock(scope=Mock(return_value=scope))
    repository = Mock(pending_authority_registrations=Mock(side_effect=lambda project, *, after_id, limit:
        [value for key, value in metadata.items() if key > after_id][:limit + 1]))
    application = ContextPackApplicationService(Mock(), auth, repository, Mock())
    application._verify_stored = Mock(side_effect=lambda project, ident, **kwargs: (metadata[ident], {}, None))
    return application, metadata


def invocation(application):
    request = ContextAuthorityBackfillInput(project_id="project", limit=1)
    return ToolInvocation(id="command", tool_id=CONTEXT_AUTHORITY_BACKFILL_TOOL, status="completed", summary="Discovery",
        input_payload=request.model_dump(), result=ToolResult(invocation_id="command", status="completed", summary="Metadata",
            context_authority_backfill=application.receipt(request)))


def test_discovery_verifies_original_cursor_lookahead_and_final_access_without_writes():
    application, metadata = service()
    receipt = application.receipt(ContextAuthorityBackfillInput(project_id="project", after_id="a", limit=1))
    assert receipt.items[0].registration_request.context_id == "b" and receipt.next_after_id == "b"
    assert [call.args[1] for call in application._verify_stored.call_args_list] == ["a", "b", "c"]
    assert all(call.kwargs == {"verify_authorities": False} for call in application._verify_stored.call_args_list)
    assert receipt.items[0].registration_request.artifact_hash == metadata["b"]["artifact_hash"]
    assert receipt.page_digest == snapshot_digest(application.pending_authority_registrations("project", after_id="a", limit=1))
    assert receipt.generation_authorized is receipt.execution_authorized is False
    application.artifacts.put.assert_not_called()
    application.repository.register_authorities.assert_not_called()


@pytest.mark.parametrize("boundary", ["cursor", "lookahead", "final_access"])
def test_discovery_never_returns_a_partial_page_when_any_original_archive_is_unreadable(boundary):
    application, metadata = service()
    def read(project, ident, **kwargs):
        if ident == ("a" if boundary == "cursor" else "c") and boundary != "final_access":
            raise SourceAccessDenied("Private fixture")
        return metadata[ident], {}, None
    application._verify_stored.side_effect = read
    if boundary == "final_access":
        application.authorization.require_current.side_effect = StaleSourceAccessScope("Private fixture")
    with pytest.raises((SourceAccessDenied, StaleSourceAccessScope)):
        application.receipt(ContextAuthorityBackfillInput(project_id="project", after_id="a", limit=1))


@pytest.mark.parametrize("role", ["viewer", "tester"])
def test_empty_discovery_still_requires_current_reviewer(role):
    application, _ = service(role)
    with pytest.raises(SourceAccessDenied):
        application.receipt(ContextAuthorityBackfillInput(project_id="project"))
    application.repository.pending_authority_registrations.assert_not_called()


@pytest.mark.parametrize("changes", [{"limit": True}, {"limit": "1"}, {"limit": 6}, {"limit": 0},
    {"after_id": "x" * 129}, {"project_id": ""}, {"confirmed": True}])
def test_discovery_input_is_strict_and_bounded(changes):
    with pytest.raises(ValidationError):
        ContextAuthorityBackfillInput.model_validate({"project_id": "project", **changes})


@pytest.mark.parametrize("change", ["order", "duplicate", "project", "cursor", "authority", "body", "hash"])
def test_receipt_rejects_fabricated_or_unbounded_registration_metadata(change):
    application, _ = service()
    value = application.receipt(ContextAuthorityBackfillInput(project_id="project", limit=2)).model_dump(mode="json")
    if change == "order":
        value["items"].reverse()
    elif change == "duplicate":
        value["items"][1] = deepcopy(value["items"][0])
    elif change == "project":
        value["items"][0]["registration_request"]["project_id"] = "foreign"
    elif change == "cursor":
        value["next_after_id"] = "foreign"
    elif change == "authority":
        value["execution_authorized"] = True
    elif change == "body":
        value["items"][0]["oracle"] = "Private content"
    else:
        value["items"][0]["registration_request"]["artifact_hash"] = "unverified"
    with pytest.raises(ValidationError):
        ContextAuthorityBackfillReceipt.model_validate(value)


def test_handler_observer_and_fingerprint_share_a_typed_revalidated_receipt():
    application, _ = service()
    command = invocation(application)
    events, access = SimpleNamespace(emit_tool_status=AsyncMock()), Mock()
    asyncio.run(ContextPackToolHandler(application, events, access).handle(command))
    result = events.emit_tool_status.call_args.args[-1]
    assert result.context_authority_backfill == command.result.context_authority_backfill and result.context_pack is None
    assert result.next_recommended_tools == ["system_image.context.register_authorities"]
    restored = ToolInvocation.model_validate_json(command.model_dump_json())
    observer = ToolContextPackObservationApplicationService(Mock(get_tool_invocation=Mock(return_value=restored)), application, access)
    assert observer.describe(restored.id, "project") == command.result.context_authority_backfill.model_dump(mode="json")
    assert observation_receipt_fingerprint(restored.result) == observation_receipt_fingerprint(command.result)
    changed = restored.result.model_copy(update={"context_authority_backfill":
        restored.result.context_authority_backfill.model_copy(update={"page_digest": "sha256:" + "0" * 64})})
    assert observation_receipt_fingerprint(changed) != observation_receipt_fingerprint(command.result)
    application.repository.pending_authority_registrations.side_effect = None
    application.repository.pending_authority_registrations.return_value = []
    with pytest.raises(PlatformApplicationError, match="changed"):
        observer.describe(command.id, "project")


@pytest.mark.parametrize("boundary", ["read", "after"])
def test_handler_drops_receipt_on_private_or_final_access_failure(boundary):
    application, _ = service()
    command = invocation(application)
    events, access = SimpleNamespace(emit_tool_status=AsyncMock()), Mock()
    if boundary == "read":
        application._verify_stored.side_effect = SourceAccessDenied("Secret credential and archive text")
    else:
        access.require_invocation_project_scope.side_effect = [None, SourceAccessDenied("Secret credential")]
    asyncio.run(ContextPackToolHandler(application, events, access).handle(command))
    result = events.emit_tool_status.call_args.args[-1]
    assert result.status == "failed" and result.context_authority_backfill is None and "Secret" not in result.model_dump_json()


@pytest.mark.parametrize("role,allowed", [("viewer", False), ("tester", False), ("qa_lead", True),
    ("project_admin", True), ("platform_admin", True)])
def test_canonical_discovery_is_readonly_but_reviewer_restricted(role, allowed):
    definition = next(tool for tool in system_image_tool_definitions() if tool.tool_id == CONTEXT_AUTHORITY_BACKFILL_TOOL)
    assert definition.tool_kind == "query" and definition.confirmation_mode == "none" and definition.required_context == ["project_id"]
    assert ToolRBAC().authorize(SimpleNamespace(role=role), definition).allowed is allowed
