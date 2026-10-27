import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from apps.api.app.application.agent.observation_receipts import observation_receipt_fingerprint
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.tool_catalog import system_image_tool_definitions
from apps.api.app.application.platform.tool_handlers.test_design_review_queries import TestDesignReviewQueryHandler
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.platform.tool_test_design_scope import ToolTestDesignScopeObservationApplicationService
from apps.api.app.application.quality_loop.test_design_review_queries import REVIEW_DRAFT_QUERY_TOOL, ReviewDraftListInput, ReviewDraftListReceipt
from apps.api.app.application.quality_loop.test_design_results import TestDesignResultApplicationService, TestDesignResultIntegrityError
from apps.api.app.domain.platform.rbac import ToolRBAC
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope


def query_service(ids=("a", "b", "c"), role="qa_lead"):
    values = {ident: {"metadata": {"project_id": "project", "generation_id": ident, "artifact_hash": "sha256:" + ident * 64},
        "result": {"context_pin": {"context_id": "context"}, "scope_pin": {"revision_id": "scope"},
                   "raw_output": "Protected text never belongs in discovery metadata"}} for ident in ids}
    access = SimpleNamespace(effective_project_role=role)
    auth = Mock(scope=Mock(return_value=access))
    repository = Mock(list_metadata=Mock(side_effect=lambda request: [values[ident]["metadata"]
        for ident in ids if ident > request.after_id][:request.limit + 1]))
    service = TestDesignResultApplicationService(Mock(), auth, Mock(), repository, Mock())
    service.read = Mock(side_effect=lambda project, ident: values[ident])
    return service, values, access


def test_discovery_checks_cursor_lookahead_and_never_grants_egress_or_execution():
    service, values, access = query_service()
    request = ReviewDraftListInput(project_id="project", limit=1)
    page = service.list_for_review(request)
    assert page == {"request": request.model_dump(), "items": [{"metadata": values["a"]["metadata"],
        "context_pin": {"context_id": "context"}, "scope_pin": {"revision_id": "scope"}}],
        "next_after_id": "a", "can_review": True, "generation_authorized": False, "execution_authorized": False}
    assert service.read.call_count == 2
    service.authorization.require_current.assert_called_once_with(access)
    second = service.list_for_review(request.model_copy(update={"after_id": "a", "limit": 2}))
    assert [item["metadata"]["generation_id"] for item in second["items"]] == ["b", "c"]
    assert second["next_after_id"] is None
    assert "Protected text" not in repr(second)
    service.generation.prepare.assert_not_called()
    service.profiles.resolve.assert_not_called()
    service.artifacts.put.assert_not_called()


@pytest.mark.parametrize("role", ["viewer", "tester"])
def test_nonreviewers_cannot_probe_an_empty_or_populated_discovery(role):
    service, _, _ = query_service(role=role)
    with pytest.raises(PermissionError):
        service.list_for_review(ReviewDraftListInput(project_id="project"))
    service.repository.list_metadata.assert_not_called()
    service.read.assert_not_called()


@pytest.mark.parametrize("boundary", ["cursor", "lookahead", "end"])
def test_discovery_never_returns_a_partial_page_after_access_changes(boundary):
    service, values, _ = query_service()
    request = ReviewDraftListInput(project_id="project", limit=1, after_id="a" if boundary == "cursor" else "")
    def read(project, ident):
        if ident == ("a" if boundary == "cursor" else "b") and boundary != "end":
            raise SourceAccessDenied("Private fixture error")
        return values[ident]
    service.read.side_effect = read
    if boundary == "end":
        service.authorization.require_current.side_effect = StaleSourceAccessScope("Changed source policy")
    with pytest.raises((SourceAccessDenied, StaleSourceAccessScope)):
        service.list_for_review(request)


@pytest.mark.parametrize("change", ["project", "order", "duplicate", "archive", "budget"])
def test_discovery_rejects_metadata_or_page_mismatch(change):
    service, values, _ = query_service()
    rows = deepcopy([value["metadata"] for value in values.values()])
    if change == "project":
        rows[0]["project_id"] = "foreign"
    elif change == "order":
        rows.reverse()
    elif change == "duplicate":
        rows[1] = rows[0]
    elif change == "archive":
        rows[0]["artifact_hash"] = "changed"
    else:
        rows *= 3
    service.repository.list_metadata.side_effect = None
    service.repository.list_metadata.return_value = rows
    with pytest.raises(TestDesignResultIntegrityError):
        service.list_for_review(ReviewDraftListInput(project_id="project", limit=2))


@pytest.mark.parametrize("changes", [{"limit": 0}, {"limit": 6}, {"limit": True}, {"limit": "1"},
    {"after_id": "a" * 129}, {"project_id": ""}, {"confirmed": True}])
def test_discovery_request_is_strict_and_bounded(changes):
    with pytest.raises(ValidationError):
        ReviewDraftListInput.model_validate({"project_id": "project", **changes})


def test_receipt_preserves_exact_page_digest_without_archived_body():
    service, _, _ = query_service()
    request = ReviewDraftListInput(project_id="project", limit=1)
    receipt = service.review_receipt(request)
    assert receipt.generation_ids == ("a",) and receipt.next_after_id == "a"
    assert receipt.page_digest == acceptance_digest(service.list_for_review(request))
    assert receipt.generation_authorized is receipt.execution_authorized is False
    assert "Protected text" not in receipt.model_dump_json()
    service.verify_review_receipt(ReviewDraftListReceipt.model_validate_json(receipt.model_dump_json()))
    service.generation.prepare.assert_not_called()
    service.profiles.resolve.assert_not_called()
    service.artifacts.put.assert_not_called()


@pytest.mark.parametrize("change", ["context", "scope", "metadata", "page", "role", "acl"])
def test_receipt_revalidation_rejects_changed_pins_pages_or_access(change):
    service, values, access = query_service()
    receipt = service.review_receipt(ReviewDraftListInput(project_id="project", limit=1))
    if change in {"context", "scope"}:
        values["a"]["result"][change + "_pin"]["artifact_hash"] = "sha256:" + "f" * 64
    elif change == "metadata":
        values["a"]["metadata"]["artifact_hash"] = "sha256:" + "f" * 64
    elif change == "page":
        service.repository.list_metadata.side_effect = None
        service.repository.list_metadata.return_value = [values["b"]["metadata"]]
    elif change == "role":
        access.effective_project_role = "viewer"
    else:
        service.authorization.require_current.side_effect = StaleSourceAccessScope("Private access changed")
    with pytest.raises((TestDesignResultIntegrityError, PermissionError, StaleSourceAccessScope)):
        service.verify_review_receipt(receipt)


@pytest.mark.parametrize("changes", [
    {"generation_ids": ["b", "a"]}, {"generation_ids": ["a", "a"]},
    {"generation_ids": [1]}, {"generation_ids": [""]},
    {"generation_ids": ["a", "b"], "request": {"project_id": "project", "limit": 1}},
    {"generation_ids": ["a"], "request": {"project_id": "project", "after_id": "a"}},
    {"generation_ids": [], "next_after_id": "a"}, {"next_after_id": "b"},
    {"page_digest": "unverified"}, {"generation_authorized": True}, {"execution_authorized": True},
    {"raw_output": "private"}, {"observation": "approved"},
])
def test_receipt_rejects_unbounded_or_fabricated_observations(changes):
    payload = {"request": {"project_id": "project", "limit": 1}, "generation_ids": ["a"],
        "page_digest": "sha256:" + "0" * 64, "next_after_id": "a", **changes}
    with pytest.raises(ValidationError):
        ReviewDraftListReceipt.model_validate(payload)


def invocation_with_receipt(service):
    request = ReviewDraftListInput(project_id="project", limit=1)
    receipt = service.review_receipt(request)
    result = ToolResult(invocation_id="command", status="completed", summary="Metadata only", test_design_review_drafts=receipt)
    return ToolInvocation(id="command", tool_id=REVIEW_DRAFT_QUERY_TOOL, status="completed", summary="Query",
        input_payload=request.model_dump(), result=result)


def test_handler_emits_typed_receipt_and_checks_access_before_and_after_read():
    service, _, _ = query_service()
    invocation = invocation_with_receipt(service)
    events, access = SimpleNamespace(emit_tool_status=AsyncMock()), Mock()
    handler = TestDesignReviewQueryHandler(service, events, access)
    asyncio.run(handler.handle(invocation))
    result = events.emit_tool_status.call_args.args[-1]
    assert result.status == "completed" and result.test_design_review_drafts == invocation.result.test_design_review_drafts
    assert access.require_invocation_project_scope.call_count == 2
    assert events.emit_tool_status.call_args_list[0].args[1] == "running"


@pytest.mark.parametrize("failure", ["before", "read", "after", "payload"])
def test_handler_never_emits_private_errors_or_ids_on_failed_discovery(failure):
    service, _, _ = query_service()
    invocation = invocation_with_receipt(service)
    events, access = SimpleNamespace(emit_tool_status=AsyncMock()), Mock()
    private = SourceAccessDenied("Secret archive ID and provider credential")
    if failure == "read":
        service.read.side_effect = private
    elif failure == "payload":
        invocation.input_payload = {"project_id": "project", "limit": True}
    else:
        access.require_invocation_project_scope.side_effect = [private] if failure == "before" else [None, private]
    asyncio.run(TestDesignReviewQueryHandler(service, events, access).handle(invocation))
    result = events.emit_tool_status.call_args.args[-1]
    assert result.status == "failed" and result.test_design_review_drafts is None
    assert "Secret" not in result.model_dump_json() and "Protected text" not in result.model_dump_json()


def test_observer_revalidates_persisted_receipt_and_fingerprint_without_body():
    service, _, _ = query_service()
    invocation = invocation_with_receipt(service)
    restored = ToolInvocation.model_validate_json(invocation.model_dump_json())
    access = Mock()
    observer = ToolTestDesignScopeObservationApplicationService(Mock(get_tool_invocation=Mock(return_value=restored)),
        Mock(), access, drafts=service)
    assert observer.describe(invocation.id, "project") == invocation.result.test_design_review_drafts.model_dump(mode="json")
    assert access.require_invocation_project_scope.call_count == 2
    assert observation_receipt_fingerprint(restored.result) == observation_receipt_fingerprint(invocation.result)
    assert observation_receipt_fingerprint(restored.result.model_copy(update={"status": "failed"})) is None
    changed = restored.result.model_copy(update={"test_design_review_drafts":
        restored.result.test_design_review_drafts.model_copy(update={"page_digest": "sha256:" + "1" * 64})})
    assert observation_receipt_fingerprint(changed) != observation_receipt_fingerprint(restored.result)


@pytest.mark.parametrize("change", ["project", "request", "missing", "service", "changed", "access"])
def test_observer_rejects_mismatched_or_no_longer_readable_observations(change):
    service, values, _ = query_service()
    invocation = invocation_with_receipt(service)
    access = Mock()
    project = "foreign" if change == "project" else "project"
    if change == "request":
        invocation.input_payload["limit"] = 2
    elif change == "missing":
        invocation.result.test_design_review_drafts = None
    elif change == "changed":
        values["a"]["result"]["scope_pin"]["artifact_hash"] = "changed"
    elif change == "access":
        access.require_invocation_project_scope.side_effect = [None, SourceAccessDenied("Changed")]
    observer = ToolTestDesignScopeObservationApplicationService(Mock(get_tool_invocation=Mock(return_value=invocation)),
        Mock(), access, drafts=None if change == "service" else service)
    with pytest.raises((PlatformApplicationError, TestDesignResultIntegrityError, SourceAccessDenied)):
        observer.describe(invocation.id, project)


@pytest.mark.parametrize("role,allowed", [("viewer", False), ("tester", False), ("qa_lead", True),
    ("project_admin", True), ("platform_admin", True)])
def test_review_discovery_query_requires_reviewer_role_even_though_it_is_read_only(role, allowed):
    definition = next(tool for tool in system_image_tool_definitions() if tool.tool_id == REVIEW_DRAFT_QUERY_TOOL)
    assert definition.tool_kind == "query" and definition.confirmation_mode == "none"
    assert definition.required_context == ["project_id"]
    assert ToolRBAC().authorize(SimpleNamespace(role=role), definition).allowed is allowed
