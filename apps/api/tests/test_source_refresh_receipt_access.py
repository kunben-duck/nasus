"""Current source permission, not historic command ownership, grants receipt reads."""
from copy import deepcopy

import pytest

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.source_refresh_receipts import SourceRefreshReceiptAccess
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.domain.system_image.source_access import (
    SourceAccessDenied, SourceAccessRule, SourceAccessSnapshot, SourceBindingAccess, StaleSourceAccessScope,
)
from apps.api.tests.test_tool_invocation_application_ports import build_service


def receipt():
    return ToolInvocation(id="original", tool_id="system_image.sources.ingest", status="completed",
        summary="Refreshed 1 selected source group.", idempotency_scope="actor:reader", idempotency_key="original-request",
        input_payload={"project_id": "project", "source_ids": ["source"], "expected_manifest_id": "manifest",
            "expected_manifest_hash": "sha256:" + "a" * 64, "idempotency_key": "original-request"},
        result=ToolResult(invocation_id="original", status="completed", summary="Refreshed",
            object_refs=["raw_asset:source"], evidence_refs=["private-evidence"]))


class Sources:
    def __init__(self):
        self.reads = []
        self.rechecks = []
        self.snapshot = SourceAccessSnapshot("project", 1, (
            SourceBindingAccess("binding", "source", SourceAccessRule("restricted", ("reader",))),))

    def scope(self, project_id):
        self.reads.append(project_id)
        return self.snapshot.for_actor("reader", "viewer")

    def require_current(self, scope):
        self.rechecks.append(scope)
        if scope.fingerprint != self.snapshot.for_actor("reader", "viewer").fingerprint:
            raise StaleSourceAccessScope("source selection changed")

    def require_all_sources_access(self, project_id):
        scope = self.scope(project_id)
        if not scope.permits_sources(tuple(item.source_id for item in self.snapshot.bindings)):
            raise SourceAccessDenied("source access was revoked")
        self.require_current(scope)
        return scope

    def require_current_many(self, scopes):
        for scope in scopes:
            self.require_current(scope)


def test_selected_receipt_reads_require_the_live_scope_without_rewriting_original_pins():
    sources, command = Sources(), receipt()
    original = deepcopy(command.model_dump())
    access = SourceRefreshReceiptAccess(sources)
    assert access.applies(command)
    access.require_access(command)
    assert sources.reads == ["project"] and len(sources.rechecks) == 1
    assert command.model_dump() == original


@pytest.mark.parametrize("field,value", [
    ("source_ids", []), ("source_ids", ["source", "source"]), ("source_ids", "source"),
    ("source_ids", ["\x00source"]), ("source_ids", [None]),
    ("expected_manifest_id", None), ("expected_manifest_id", " manifest"),
    ("expected_manifest_hash", "sha256:" + "A" * 64), ("expected_manifest_hash", "invalid"),
    ("project_id", None), ("project_id", ""),
])
def test_invalid_receipt_scope_is_rejected_before_source_access(field, value):
    command, sources = receipt(), Sources()
    command.input_payload[field] = value
    with pytest.raises(PlatformApplicationError) as denied:
        SourceRefreshReceiptAccess(sources).require_access(command)
    assert denied.value.status_code == 409
    assert sources.reads == sources.rechecks == []


def test_membership_does_not_grant_a_revoked_or_unknown_selected_source():
    sources, command = Sources(), receipt()
    sources.snapshot = SourceAccessSnapshot("project", 2, (
        SourceBindingAccess("binding", "source", SourceAccessRule("restricted")),))
    access = SourceRefreshReceiptAccess(sources)
    for source_ids in (["source"], ["unknown"], ["source", "unknown"]):
        command.input_payload["source_ids"] = source_ids
        with pytest.raises(PlatformApplicationError) as denied:
            access.require_access(command)
        assert denied.value.status_code == 403
        assert all(ident not in denied.value.message for ident in source_ids)
    assert sources.rechecks == []


@pytest.mark.parametrize("error", [SourceAccessDenied, StaleSourceAccessScope, KeyError])
def test_live_scope_failure_is_sanitized_without_original_source_or_manifest(monkeypatch, error):
    sources, command = Sources(), receipt()

    def revoked(_):
        raise error("private-evidence original-request manifest")

    monkeypatch.setattr(sources, "scope", revoked)
    with pytest.raises(PlatformApplicationError) as denied:
        SourceRefreshReceiptAccess(sources).require_access(command)
    assert denied.value.status_code == 403
    assert "private-evidence" not in denied.value.message and "original-request" not in denied.value.message


def test_permission_changes_between_scope_and_return_reject_the_original_receipt(monkeypatch):
    sources, command = Sources(), receipt()
    current = sources.require_current

    def revoke(scope):
        sources.snapshot = SourceAccessSnapshot("project", 2, ())
        current(scope)

    monkeypatch.setattr(sources, "require_current", revoke)
    with pytest.raises(PlatformApplicationError) as denied:
        SourceRefreshReceiptAccess(sources).require_access(command)
    assert denied.value.status_code == 403 and len(sources.rechecks) == 1


def test_shared_receipts_hide_source_payloads_without_mutating_persisted_history():
    sources, command = Sources(), receipt()
    original = deepcopy(command.model_dump())
    view = SourceRefreshReceiptAccess(sources).broadcast_view(command)
    assert view is not command and view.input_payload == {} and view.result is None
    assert view.idempotency_key is view.idempotency_scope is view.idempotency_fingerprint is None
    assert (view.id, view.status) == (command.id, command.status)
    assert view.summary == "Source ingestion status: completed."
    view.status = "failed"
    assert command.model_dump() == original
    assert sources.reads == sources.rechecks == []


def test_legacy_whole_project_receipts_require_all_sources_and_other_commands_remain_unchanged():
    sources, command = Sources(), receipt()
    access = SourceRefreshReceiptAccess(sources)
    command.input_payload.pop("source_ids")
    access.require_access(command)
    assert sources.reads == ["project"] and len(sources.rechecks) == 1
    assert access.broadcast_view(command).input_payload == {}
    sources.snapshot = SourceAccessSnapshot("project", 2, (
        SourceBindingAccess("binding", "source", SourceAccessRule("restricted")),))
    with pytest.raises(PlatformApplicationError) as denied:
        access.require_access(command)
    assert denied.value.status_code == 403
    command.tool_id = "run.progress.get"
    command.input_payload["source_ids"] = ["source"]
    access.require_access(command)
    assert access.broadcast_view(command) is command


def test_targeted_receipt_reads_fail_closed_when_the_source_port_is_unavailable(monkeypatch):
    service, state, _, _, _ = build_service()
    command = receipt()
    state.invocations[command.id] = command
    monkeypatch.setattr(state, "find_idempotent_invocation", lambda **_: command, raising=False)
    for read in (
        lambda: service.get_tool_invocation(command.id),
        lambda: service.resolve_owned_tool_invocation(actor_id="reader", project_id="project",
            tool_id=command.tool_id, request_key="original-request"),
    ):
        with pytest.raises(PlatformApplicationError) as denied:
            read()
        assert denied.value.status_code == 503
    with pytest.raises(PlatformApplicationError) as unavailable:
        service.list_tool_invocations(tool_id=command.tool_id)
    assert unavailable.value.status_code == 503


@pytest.mark.parametrize("whole_project", [False, True])
def test_receipt_batch_groups_one_project_without_rewriting_command_pins(whole_project):
    sources, first = Sources(), receipt()
    second = first.model_copy(update={"id": "second"}, deep=True)
    if whole_project:
        second.input_payload.pop("source_ids")
    original = [item.model_dump() for item in (first, second)]
    SourceRefreshReceiptAccess(sources).require_batch_access((first, second))
    assert sources.reads == ["project"]
    assert len(sources.rechecks) == (2 if whole_project else 1)
    assert [item.model_dump() for item in (first, second)] == original


def test_empty_or_unrelated_batches_do_not_require_source_or_bulk_authorization():
    sources, command = Sources(), receipt()
    command.tool_id = "run.progress.get"
    access = SourceRefreshReceiptAccess(sources)
    access.require_batch_access(())
    access.require_batch_access((command,))
    assert sources.reads == sources.rechecks == []


@pytest.mark.parametrize("fault", ["missing_bulk", "unavailable_bulk", "unavailable_scope", "oversized"])
def test_receipt_batch_authorization_unavailability_fails_closed(monkeypatch, fault):
    sources, command = Sources(), receipt()
    commands = [command]

    def unavailable(_):
        raise RuntimeError("private-source manifest URI must not escape")

    if fault == "missing_bulk":
        monkeypatch.setattr(sources, "require_current_many", None)
    elif fault == "unavailable_bulk":
        monkeypatch.setattr(sources, "require_current_many", unavailable)
    elif fault == "unavailable_scope":
        monkeypatch.setattr(sources, "scope", unavailable)
    else:
        commands = [command.model_copy(update={"input_payload": {**command.input_payload,
            "project_id": f"project-{index}"}}, deep=True) for index in range(129)]
    with pytest.raises(PlatformApplicationError) as denied:
        SourceRefreshReceiptAccess(sources).require_batch_access(commands)
    assert denied.value.status_code == 503 and "private-source" not in denied.value.message
    if fault in {"missing_bulk", "oversized"}:
        assert sources.reads == sources.rechecks == []


@pytest.mark.parametrize("change", ["revoke", "epoch", "unknown_source", "foreign_project"])
def test_receipt_batch_rejects_changed_or_invalid_scopes(monkeypatch, change):
    sources, command = Sources(), receipt()
    original = sources.require_current_many

    def changed(scopes):
        sources.snapshot = SourceAccessSnapshot("project", 2, ())
        original(scopes)

    if change == "revoke":
        sources.snapshot = SourceAccessSnapshot("project", 2, (
            SourceBindingAccess("binding", "source", SourceAccessRule("restricted")),))
    elif change == "epoch":
        monkeypatch.setattr(sources, "require_current_many", changed)
    elif change == "unknown_source":
        command.input_payload["source_ids"] = ["unknown-source"]
    else:
        sources.snapshot = SourceAccessSnapshot("other", 1, sources.snapshot.bindings)
    with pytest.raises(PlatformApplicationError) as denied:
        SourceRefreshReceiptAccess(sources).require_batch_access((command,))
    assert denied.value.status_code == 403
