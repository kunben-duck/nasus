"""A partial receipt list is not proof that inaccessible history is absent."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.tool_models import AuditEvent, ToolInvocation
from apps.api.tests.test_tool_invocation_application_ports import build_service


def history():
    service, state, runtime, _, _ = build_service()
    for index in range(2):
        command = ToolInvocation(id=f"original-{index}", tool_id="system_image.sources.ingest",
            status="completed", summary="Original source receipt",
            input_payload={"project_id": "project", "source_ids": [f"source-{index}"]})
        state.invocations[command.id] = command
        state.audit_events.append(AuditEvent(id=f"audit-{index}",
            occurred_at=f"2026-01-01T00:00:0{index}+00:00", actor="system",
            action="tool.invocation.created", entity_type="tool_invocation", entity_id=command.id,
            tool_invocation_id=command.id, summary="Original receipt"))
    return service, state, runtime


@pytest.mark.parametrize("endpoint", ["invocations", "audit"])
@pytest.mark.parametrize("status", [409, 422, 500, 502, 503, 504])
def test_late_verification_fault_discards_the_entire_receipt_list(endpoint, status):
    service, state, runtime = history()
    before = deepcopy([item.model_dump(mode="json") for item in state.invocations.values()])
    checked, cohorts = [], []
    fault = PlatformApplicationError("receipt_verification_failed", "Original receipt could not be verified.", status)

    def verify(command):
        checked.append(command.id)
        if command.id == "original-1":
            raise fault

    service._read_resources = SimpleNamespace(require_access=verify,
        require_batch_access=lambda items: cohorts.append(items))
    read = service.list_tool_invocations if endpoint == "invocations" else service.list_audit_events
    with pytest.raises(PlatformApplicationError) as raised:
        read()
    assert raised.value is fault and checked == ["original-0", "original-1"]
    assert cohorts == []
    assert [item.model_dump(mode="json") for item in state.invocations.values()] == before
    assert runtime.created_payloads == runtime.confirmed_ids == []


@pytest.mark.parametrize("endpoint", ["invocations", "audit"])
@pytest.mark.parametrize("tool_id", ["system_image.sources.ingest", "quality.run_plan.prepare",
    "quality.http_fixture.authorize"])
def test_missing_required_authorization_is_not_an_empty_success(endpoint, tool_id):
    service, state, runtime = history()
    for command in state.invocations.values():
        command.tool_id = tool_id
    read = service.list_tool_invocations if endpoint == "invocations" else service.list_audit_events
    with pytest.raises(PlatformApplicationError) as raised:
        read()
    assert raised.value.status_code == 503
    assert runtime.created_payloads == runtime.confirmed_ids == []


@pytest.mark.parametrize("endpoint", ["invocations", "audit"])
def test_only_permission_denial_can_filter_a_record_from_a_new_list(endpoint):
    service, state, _ = history()
    cohorts = []

    def verify(command):
        if command.id == "original-1":
            raise PlatformApplicationError("source_access_denied", "Source is not available.", 403)

    service._read_resources = SimpleNamespace(require_access=verify,
        require_batch_access=lambda items: cohorts.append([item.id for item in items]))
    read = service.list_tool_invocations if endpoint == "invocations" else service.list_audit_events
    assert [item.id for item in read()] == ["original-0" if endpoint == "invocations" else "audit-0"]
    assert cohorts == [["original-0"]]
    assert len(state.invocations) == len(state.audit_events) == 2
