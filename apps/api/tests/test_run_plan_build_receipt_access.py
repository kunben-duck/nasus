"""Original build receipt access and lifecycle-only public projections."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.run_plan_build_receipts import RunPlanBuildReceiptAccess, RUN_PLAN_BUILD_RECEIPT_TOOLS
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.platform.tool_receipt_access import require_receipt_access
from apps.api.app.application.quality_loop.run_plan_build_inputs import RunPlanBuildQuery, RunPlanBuildRequest
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_run_plan_builds import application, binding_inputs


def command(tool):
    _, selection, _ = binding_inputs()
    payload = ({"project_id": "p", "binding_id": "original"} if tool == "query.quality.run_plan_build"
               else selection.model_dump(mode="json"))
    return ToolInvocation(id="original", tool_id=tool, status="waiting_confirmation", summary="private reason",
        input_payload={**payload, "idempotency_key": "private-key"}, idempotency_key="private-key",
        result=ToolResult(invocation_id="original", status="completed", summary="private result"))


@pytest.mark.parametrize("tool", sorted(RUN_PLAN_BUILD_RECEIPT_TOOLS))
def test_binding_original_scope_reauthorized_and_broadcast_never_contains_receipt(tool):
    calls = []
    port = SimpleNamespace(require_receipt_inputs_access=lambda scope: calls.append(scope),
        require_receipt_inputs_access_many=lambda scopes: calls.append(scopes))
    value = command(tool)
    original = deepcopy(value.model_dump())
    access = RunPlanBuildReceiptAccess(port)
    access.require_access(value)
    access.require_batch_access((value, value.model_copy(update={"id": "replay"}, deep=True)))
    assert len(calls) == 2 and len(calls[1]) == 1 and calls[0] == calls[1][0]
    projected = access.broadcast_view(value)
    assert projected.input_payload == {} and projected.result is None and projected.idempotency_key is None
    assert "private" not in str(projected.model_dump()) and value.model_dump() == original
    def deny(*args):
        raise SourceAccessDenied("private source revocation")
    port.require_receipt_inputs_access = port.require_receipt_inputs_access_many = deny
    for operation in (lambda: access.require_access(value), lambda: access.require_batch_access((value,))):
        with pytest.raises(PlatformApplicationError) as denied:
            operation()
        assert denied.value.status_code == 403 and "private" not in str(denied.value)


@pytest.mark.parametrize("tool", sorted(RUN_PLAN_BUILD_RECEIPT_TOOLS))
def test_binding_receipt_requires_its_actual_access_port_and_complete_original_scope(tool):
    value = command(tool)
    with pytest.raises(PlatformApplicationError) as absent:
        require_receipt_access(None, value)
    assert absent.value.status_code == 503
    with pytest.raises(PlatformApplicationError) as unavailable:
        RunPlanBuildReceiptAccess(object()).require_access(value)
    assert unavailable.value.status_code == 503
    value.input_payload.pop("project_id")
    with pytest.raises(PlatformApplicationError) as malformed:
        RunPlanBuildReceiptAccess(object()).require_access(value)
    assert malformed.value.status_code == 409


def test_application_receipt_replay_is_readonly_historical_and_checks_final_acl():
    service, view, selection, auth, actions, stored = application()
    service.require_receipt_inputs_access(selection)
    assert "put" not in actions and not stored
    request = RunPlanBuildRequest.model_validate(service.preview(selection)["request"])
    metadata = service.bind(request, invocation_id="original", recorded_at="2026-10-10T00:00:00Z")
    original = deepcopy(stored)
    view["current_use"]["inputs_current"] = False
    actions.clear()
    query = RunPlanBuildQuery(project_id="p", binding_id=metadata["binding_id"])
    service.require_receipt_inputs_access_many((selection, query))
    assert "put" not in actions and stored == original
    read = service.builds.read
    def late_revoke(*args):
        value = read(*args)
        auth.revoked = True
        return value
    service.builds.read = late_revoke
    with pytest.raises(SourceAccessDenied):
        service.require_receipt_inputs_access(selection)
    assert stored == original


def test_original_preview_can_use_its_existing_default_policy_without_a_synthetic_null():
    value = command("query.quality.run_plan_build_preview")
    value.input_payload.pop("policy_revision")
    calls = []
    RunPlanBuildReceiptAccess(SimpleNamespace(require_receipt_inputs_access=lambda scope: calls.append(scope))).require_access(value)
    assert calls[0].policy_revision == "nasus.run-plan-build.v1"
